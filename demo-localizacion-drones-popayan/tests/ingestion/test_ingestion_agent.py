import math
from datetime import datetime, timedelta, timezone

import pytest

from src.contracts import (
    DataOrigin,
    IngestionResult,
    LocationRole,
    RawEvent,
    RejectedInput,
    SensorType,
)
from src.ingestion import IngestionAgent


@pytest.fixture
def agent():
    return IngestionAgent()


def test_agent_identity():
    assert IngestionAgent.name == "agent_ingestion"
    assert isinstance(IngestionAgent.version, str) and IngestionAgent.version


def test_valid_remote_id(agent, f):
    res = agent.ingest(f.rid_event())
    assert isinstance(res, IngestionResult)
    obs = res.observation
    assert obs.sensor_type == SensorType.REMOTE_ID
    assert obs.station_id == "CIV-01"
    assert obs.object_id == "SIM-UAS-0002"
    assert (obs.latitude, obs.longitude) == (2.4452, -76.6021)
    assert {loc.role for loc in res.related_locations} == {LocationRole.CONTROL_STATION, LocationRole.TAKEOFF_POINT}


def test_malformed_remote_id_payload(agent, f):
    res = agent.ingest(f.rid_event(payload={"esto": "no es rid"}))
    assert isinstance(res, RejectedInput)
    assert res.stage == "ingestion" and res.reason_code == "UNSUPPORTED_VERSION"
    assert res.station_id == "CIV-01" and res.received_at_utc == f.RECEIVED


def test_unsupported_version(agent, f):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(schema_version="rid-demo-7")))
    assert res.reason_code == "UNSUPPORTED_VERSION"


def test_schema_error_keeps_traceability(agent, f):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(drone__latitude="2.44")))
    assert res.reason_code == "SCHEMA_ERROR"
    assert res.raw_reference == "rid-demo-1:CIV-01:ing-msg-001"
    assert res.event_id is not None and res.event_id.startswith("rid-")


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"drone__latitude": 91.0}, "OUT_OF_RANGE"),
        ({"drone__longitude": -181.0}, "OUT_OF_RANGE"),
        ({"drone__latitude": 0.0, "drone__longitude": 0.0}, "POSITION_SENTINEL"),
        ({"timestamp_utc": "2026-01-15T15:05:00Z"}, "FUTURE_TIMESTAMP"),
        ({"timestamp_utc": "2026-01-15T14:00:00Z"}, "STALE"),
        ({"timestamp_utc": "2026-01-15T15:00:00"}, "TIMESTAMP_NO_TZ"),
        ({"drone__height_agl_m": 30.0}, "INCOHERENT_FIELDS"),
        ({"drone__track_deg": 361.0}, "OUT_OF_RANGE"),
    ],
)
def test_remote_id_validation_rejections(agent, f, overrides, code):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(**overrides)))
    assert isinstance(res, RejectedInput)
    assert res.stage == "ingestion"
    assert res.reason_code == code


def test_drone_without_control_station(agent, f):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(operator=None)))
    assert isinstance(res, IngestionResult)
    assert "estación de control no reportada" in res.warnings
    assert [loc.role for loc in res.related_locations] == [LocationRole.TAKEOFF_POINT]


def test_takeoff_without_controller(agent, f):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(operator=None)))
    assert "punto de despegue reportado sin estación de control" in res.warnings
    assert all(loc.role != LocationRole.CONTROL_STATION for loc in res.related_locations)


def test_without_drone_position(agent, f):
    res = agent.ingest(f.rid_event(payload=f.rid_payload(drone=None)))
    assert isinstance(res, IngestionResult)
    assert res.observation.has_position is False
    assert any("posición del dron no reportada" in w for w in res.warnings)


def test_acoustic_without_coordinates_accepted(agent, f):
    res = agent.ingest(f.obs_event())
    assert isinstance(res, IngestionResult)
    assert res.observation.sensor_type == SensorType.ACOUSTIC
    assert res.observation.has_position is False
    assert res.related_locations == []


@pytest.mark.parametrize(
    "extra", [{"latitude": 2.44, "longitude": -76.60}, {"altitude": 50.0, "altitude_reference": "agl"}]
)
def test_acoustic_with_coordinates_rejected(agent, f, extra):
    res = agent.ingest(f.obs_event(payload=f.obs_payload(**extra)))
    assert isinstance(res, RejectedInput)
    assert res.reason_code == "ACOUSTIC_WITH_POSITION"
    assert res.event_id == "obs-ac-001"


def test_observation_schema_errors(agent, f):
    assert agent.ingest(f.obs_event(payload=f.obs_payload(classifier_score="0.9"))).reason_code == "SCHEMA_ERROR"
    assert agent.ingest(f.obs_event(payload=f.obs_payload(sensor_type="sonar"))).reason_code == "SCHEMA_ERROR"
    assert agent.ingest(f.obs_event(payload=f.obs_payload(event_id=None))).reason_code == "SCHEMA_ERROR"
    assert agent.ingest(f.obs_event(payload=f.obs_payload(classifier_score=1.5))).reason_code == "SCHEMA_ERROR"
    assert agent.ingest(f.obs_event(payload=f.obs_payload(timestamp_utc="2026-01-15T15:00:00"))).reason_code == "TIMESTAMP_NO_TZ"
    assert agent.ingest(f.obs_event(payload=f.obs_payload(classifier_score=math.nan))).reason_code == "NON_FINITE_VALUE"


def test_observation_station_mismatch(agent, f):
    res = agent.ingest(f.obs_event(payload=f.obs_payload(station_id="CIV-05")))
    assert res.reason_code == "STATION_MISMATCH"


def test_optical_with_null_island_rejected(agent, f):
    payload = f.obs_payload(sensor_type="optical", latitude=0.0, longitude=0.0)
    assert agent.ingest(f.obs_event(payload=payload)).reason_code == "POSITION_SENTINEL"


# --------------------------- simulado vs real ------------------------------ #

def test_simulated_flag_preserved_remote_id(f):
    agent = IngestionAgent()
    sim = agent.ingest(f.rid_event(payload=f.rid_payload(is_simulated=True)))
    real = agent.ingest(f.rid_event(payload=f.rid_payload(is_simulated=False, message_id="ing-real-1")))
    assert (sim.observation.data_origin, sim.observation.is_simulated) == (DataOrigin.SIMULATION, True)
    assert (real.observation.data_origin, real.observation.is_simulated) == (DataOrigin.REPLAY, False)


def test_real_origin_configurable(f):
    agent = IngestionAgent(real_data_origin=DataOrigin.SENSOR)
    res = agent.ingest(f.rid_event(payload=f.rid_payload(is_simulated=False)))
    assert res.observation.data_origin == DataOrigin.SENSOR and res.observation.is_simulated is False
    with pytest.raises(ValueError):
        IngestionAgent(real_data_origin=DataOrigin.SIMULATION)


def test_simulated_flag_preserved_observation(agent, f):
    payload = f.obs_payload(sensor_type="rf", data_origin="replay", is_simulated=False)
    res = agent.ingest(f.obs_event(payload=payload))
    assert (res.observation.data_origin, res.observation.is_simulated) == (DataOrigin.REPLAY, False)


def test_observation_simulation_flag_incoherent(agent, f):
    res = agent.ingest(f.obs_event(payload=f.obs_payload(data_origin="replay", is_simulated=True)))
    assert res.reason_code == "SIMULATION_FLAG_MISMATCH"
    res = agent.ingest(f.obs_event(payload=f.obs_payload(data_origin="simulation", is_simulated=False)))
    assert res.reason_code == "SIMULATION_FLAG_MISMATCH"


def test_expect_simulated_rejects_real_flag(f):
    agent = IngestionAgent(expect_simulated=True)
    res = agent.ingest(f.rid_event(payload=f.rid_payload(is_simulated=False)))
    assert res.reason_code == "SIMULATION_FLAG_MISMATCH"
    res = agent.ingest(f.obs_event(payload=f.obs_payload(sensor_type="rf", data_origin="replay", is_simulated=False)))
    assert res.reason_code == "SIMULATION_FLAG_MISMATCH"
    assert isinstance(agent.ingest(f.rid_event()), IngestionResult)


# --------------------------- robustez ------------------------------------- #

def test_received_at_without_zone(agent, f):
    res = agent.ingest(f.rid_event(received=datetime(2026, 1, 15, 15, 0, 1)))
    assert res.reason_code == "INVALID_RECEIVED_AT"


def test_received_at_with_offset_normalized(agent, f):
    received = (f.RECEIVED).astimezone(timezone(timedelta(hours=-5)))
    res = agent.ingest(f.rid_event(received=received))
    assert isinstance(res, IngestionResult)


def test_accepts_raw_event_as_dict(agent, f):
    res = agent.ingest(f.rid_event().model_dump(mode="json"))
    assert isinstance(res, IngestionResult)


def test_deterministic(agent, f):
    assert agent.ingest(f.rid_event()) == agent.ingest(f.rid_event())


def _constructed(**fields):
    base = dict(kind="remote_id", station_id="CIV-01",
                received_at_utc=datetime(2026, 1, 15, 15, 0, 0, 500000, tzinfo=timezone.utc), payload={})
    base.update(fields)
    return RawEvent.model_construct(**base)


GARBAGE_EVENTS = [
    None, 0, 3.14, "texto", b"\x00\xff", [], [1, 2], {}, {"kind": "remote_id"}, object(),
    {"kind": "radar", "station_id": "CIV-01", "received_at_utc": "2026-01-15T15:00:00Z", "payload": {}},
    _constructed(payload=None),
    _constructed(payload="{roto"),
    _constructed(payload=[1, 2, 3]),
    _constructed(payload={"schema_version": "rid-demo-1"}),
    _constructed(payload={"schema_version": "rid-demo-1", "message_id": ["x"], "timestamp_utc": None}),
    _constructed(payload={"schema_version": "rid-demo-1", "message_id": "m", "timestamp_utc": "2026-01-15T15:00:00Z",
                          "is_simulated": True, "drone": {"latitude": 1e309, "longitude": -76.6}}),
    _constructed(kind="observation", payload=None),
    _constructed(kind="observation", payload={"sensor_type": ["acoustic"], "latitude": {}}),
    _constructed(kind="observation", payload={"event_id": "x" * 10000}),
    _constructed(kind="desconocido"),
    _constructed(station_id=None),
    _constructed(station_id=""),
    _constructed(station_id=123),
    _constructed(station_id="S" * 65),
    _constructed(received_at_utc="ayer"),
    _constructed(received_at_utc=None),
]


@pytest.mark.parametrize("event", GARBAGE_EVENTS)
def test_agent_never_raises(agent, event):
    res = agent.ingest(event)
    assert isinstance(res, RejectedInput)
    assert res.stage == "ingestion"
    assert res.reason_code and res.reason


def test_agent_never_raises_with_fuzzed_payloads(agent, f):
    """Mutaciones deterministas del mensaje válido: el agente nunca lanza."""
    values = [None, "", "x", -1, 0, 1e308, -1e308, True, [], {}, "2026-13-45T99:99:99Z", 2.4452]
    base = f.rid_payload()
    fields = list(base.keys()) + [f"drone__{k}" for k in base["drone"]] + [f"operator__{k}" for k in base["operator"]]
    count = 0
    for field in fields:
        for value in values:
            payload = f.rid_payload()
            if "__" in field:
                parent, child = field.split("__")
                payload[parent][child] = value
            else:
                payload[field] = value
            res = agent.ingest(f.rid_event(payload=payload))
            assert isinstance(res, (IngestionResult, RejectedInput))
            count += 1
    assert count > 200
