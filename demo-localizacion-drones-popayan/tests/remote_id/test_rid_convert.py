from datetime import datetime, timedelta, timezone

import pytest

from src.contracts import AltitudeReference, DataOrigin, LocationRole, SensorType
from src.remote_id import make_event_id, parse_remote_id, to_ingestion_result
from src.remote_id.convert import (
    WARN_NO_CONTROL_STATION,
    WARN_NO_DRONE_POSITION,
    WARN_NO_TAKEOFF,
    WARN_TAKEOFF_WITHOUT_CONTROL,
)

T0 = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
RECEIVED = T0 + timedelta(milliseconds=500)



def convert(raw, **kw):
    return to_ingestion_result(parse_remote_id(raw), "CIV-01", RECEIVED, **kw)


def test_full_message(make_msg):
    res = convert(make_msg())
    obs = res.observation
    assert obs.sensor_type == SensorType.REMOTE_ID
    assert obs.object_id == "SIM-UAS-0001"
    assert (obs.latitude, obs.longitude) == (2.4452, -76.6021)       # posición del DRON
    assert obs.altitude == 1795.0 and obs.altitude_reference == AltitudeReference.WGS84
    assert obs.measurement_uncertainty == 3.0
    assert obs.data_origin == DataOrigin.SIMULATION and obs.is_simulated is True
    assert obs.raw_reference == "rid-demo-1:CIV-01:test-msg-001"
    assert obs.station_id == "CIV-01"
    roles = {loc.role: loc for loc in res.related_locations}
    assert set(roles) == {LocationRole.CONTROL_STATION, LocationRole.TAKEOFF_POINT}
    assert (roles[LocationRole.CONTROL_STATION].latitude, roles[LocationRole.CONTROL_STATION].longitude) == (2.4431, -76.6049)
    assert roles[LocationRole.CONTROL_STATION].detail == "live_gnss"
    assert (roles[LocationRole.TAKEOFF_POINT].latitude, roles[LocationRole.TAKEOFF_POINT].longitude) == (2.4433, -76.6047)
    assert WARN_NO_CONTROL_STATION not in res.warnings


def test_operator_id_never_used(make_msg):
    res = convert(make_msg(operator_id="OP-FICTICIO-000"))
    dumped = res.model_dump_json()
    assert "OP-FICTICIO-000" not in dumped
    res2 = convert(make_msg(uas_id=None, operator_id="OP-FICTICIO-000"))
    assert res2.observation.object_id is None


def test_drone_without_control_station(make_msg):
    res = convert(make_msg(operator=None))
    assert WARN_NO_CONTROL_STATION in res.warnings
    assert [loc.role for loc in res.related_locations] == [LocationRole.TAKEOFF_POINT]
    assert res.observation.latitude == 2.4452  # no se sustituye por nada


def test_takeoff_without_controller(make_msg):
    res = convert(make_msg(operator=None))
    assert WARN_TAKEOFF_WITHOUT_CONTROL in res.warnings
    takeoff = res.related_locations[0]
    # el punto de despegue NO se promueve a estación de control
    assert takeoff.role == LocationRole.TAKEOFF_POINT
    assert all(loc.role != LocationRole.CONTROL_STATION for loc in res.related_locations)


def test_no_operator_no_takeoff(make_msg):
    res = convert(make_msg(operator=None, takeoff=None))
    assert res.related_locations == []
    assert WARN_NO_CONTROL_STATION in res.warnings and WARN_NO_TAKEOFF in res.warnings


def test_without_drone_position(make_msg):
    res = convert(make_msg(drone=None))
    obs = res.observation
    assert obs.latitude is None and obs.longitude is None and obs.altitude is None
    assert obs.measurement_uncertainty is None
    assert WARN_NO_DRONE_POSITION in res.warnings
    # la estación de control sigue en related_locations y nunca ocupa la posición del dron
    assert {loc.role for loc in res.related_locations} == {LocationRole.CONTROL_STATION, LocationRole.TAKEOFF_POINT}


@pytest.mark.parametrize(
    "drone_overrides, expected",
    [
        ({}, (1795.0, AltitudeReference.WGS84)),
        ({"drone__altitude_geodetic_m": None}, (1792.5, AltitudeReference.MSL)),
        ({"drone__altitude_geodetic_m": None, "drone__altitude_pressure_m": None}, (55.0, AltitudeReference.TAKEOFF)),
        ({"drone__altitude_geodetic_m": None, "drone__altitude_pressure_m": None, "drone__height_reference": "agl"},
         (55.0, AltitudeReference.AGL)),
        ({"drone__altitude_geodetic_m": None, "drone__altitude_pressure_m": None, "drone__height_agl_m": None},
         (None, None)),
    ],
)
def test_altitude_selection_order(make_msg, drone_overrides, expected):
    raw = make_msg()
    for key, value in drone_overrides.items():
        raw["drone"][key.split("__")[1]] = value
    obs = convert(raw).observation
    assert (obs.altitude, obs.altitude_reference) == expected


def test_missing_accuracy_gives_unknown_uncertainty(make_msg):
    raw = make_msg()
    raw["drone"]["horizontal_accuracy_m"] = None
    res = convert(raw)
    assert res.observation.measurement_uncertainty is None
    assert any("precisión horizontal" in w for w in res.warnings)


def test_simulated_vs_real_origin(make_msg):
    sim = convert(make_msg(is_simulated=True), data_origin=DataOrigin.REPLAY)
    assert (sim.observation.data_origin, sim.observation.is_simulated) == (DataOrigin.SIMULATION, True)
    real = convert(make_msg(is_simulated=False))
    assert (real.observation.data_origin, real.observation.is_simulated) == (DataOrigin.REPLAY, False)
    sensor = convert(make_msg(is_simulated=False), data_origin=DataOrigin.SENSOR)
    assert (sensor.observation.data_origin, sensor.observation.is_simulated) == (DataOrigin.SENSOR, False)
    with pytest.raises(ValueError):
        convert(make_msg(is_simulated=False), data_origin=DataOrigin.SIMULATION)


def test_event_id_is_deterministic_and_station_scoped(make_msg):
    a = convert(make_msg()).observation.event_id
    b = convert(make_msg()).observation.event_id
    assert a == b == make_event_id("CIV-01", "test-msg-001")
    assert make_event_id("CIV-02", "test-msg-001") != a
    assert len(a) <= 128


def test_invalid_message_refused(make_msg):
    with pytest.raises(ValueError):
        convert(make_msg(drone__latitude=95.0))


def test_latency_warning(make_msg):
    msg = parse_remote_id(make_msg())
    res = to_ingestion_result(msg, "CIV-01", RECEIVED + timedelta(seconds=30))
    assert any("retraso" in w for w in res.warnings)
