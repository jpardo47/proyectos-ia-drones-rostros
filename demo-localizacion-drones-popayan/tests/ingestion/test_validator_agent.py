from datetime import datetime, timedelta, timezone

import pytest

from src.contracts import (
    IngestionResult,
    LocationRole,
    Observation,
    RejectedInput,
    ReportedLocation,
    load_default_stations,
)
from src.ingestion import IngestionAgent, ValidatorAgent

KNOWN = {s.station_id for s in load_default_stations()}


@pytest.fixture
def ingested(f):
    res = IngestionAgent().ingest(f.rid_event())
    assert isinstance(res, IngestionResult)
    return res


def test_identity_and_defaults():
    v = ValidatorAgent()
    assert ValidatorAgent.name == "agent_validator" and ValidatorAgent.version
    assert (v.max_age_s, v.max_future_s, v.known_station_ids) == (120.0, 5.0, None)


def test_valid_passes(ingested, f):
    res = ValidatorAgent(KNOWN).validate(ingested, f.RECEIVED)
    assert isinstance(res, IngestionResult)
    assert res.observation == ingested.observation
    assert res.related_locations == ingested.related_locations


def test_unknown_station(f):
    ingested = IngestionAgent().ingest(f.rid_event(station="CIV-99"))
    assert isinstance(ingested, IngestionResult)  # la ingesta no conoce el catálogo
    res = ValidatorAgent(KNOWN).validate(ingested, f.RECEIVED)
    assert isinstance(res, RejectedInput)
    assert (res.stage, res.reason_code, res.station_id) == ("validation", "UNKNOWN_STATION", "CIV-99")
    assert res.event_id == ingested.observation.event_id


def test_station_check_disabled_with_none_and_strict_with_empty(ingested, f):
    assert isinstance(ValidatorAgent(None).validate(ingested, f.RECEIVED), IngestionResult)
    assert ValidatorAgent(set()).validate(ingested, f.RECEIVED).reason_code == "UNKNOWN_STATION"


def test_stale(ingested, f):
    v = ValidatorAgent(KNOWN)
    assert isinstance(v.validate(ingested, f.T0 + timedelta(seconds=120)), IngestionResult)
    res = v.validate(ingested, f.T0 + timedelta(seconds=120.001))
    assert res.reason_code == "STALE"


def test_future(ingested, f):
    v = ValidatorAgent(KNOWN, max_future_s=5.0)
    assert isinstance(v.validate(ingested, f.T0 - timedelta(seconds=5)), IngestionResult)
    assert v.validate(ingested, f.T0 - timedelta(seconds=6)).reason_code == "FUTURE_TIMESTAMP"


def test_custom_tolerances(ingested, f):
    assert ValidatorAgent(max_age_s=10).validate(ingested, f.T0 + timedelta(seconds=11)).reason_code == "STALE"
    with pytest.raises(ValueError):
        ValidatorAgent(max_age_s=-1)


def test_acoustic_without_coordinates_passes(f):
    ingested = IngestionAgent().ingest(f.obs_event())
    res = ValidatorAgent(KNOWN).validate(ingested, f.RECEIVED)
    assert isinstance(res, IngestionResult) and res.observation.has_position is False


def test_naive_clock_rejected(ingested):
    res = ValidatorAgent().validate(ingested, datetime(2026, 1, 15, 15, 0, 1))
    assert res.reason_code == "INVALID_CLOCK"


def test_drone_role_in_related_locations_rejected(ingested, f):
    bad = ingested.model_copy(update={"related_locations": [
        ReportedLocation(role=LocationRole.DRONE, latitude=2.44, longitude=-76.60)]})
    assert ValidatorAgent().validate(bad, f.RECEIVED).reason_code == "INCOHERENT_FIELDS"


@pytest.mark.parametrize(
    "loc, code",
    [
        (dict(latitude=95.0, longitude=-76.6), "OUT_OF_RANGE"),
        (dict(latitude=2.44, longitude=float("nan")), "OUT_OF_RANGE"),
        (dict(latitude=0.0, longitude=0.0), "POSITION_SENTINEL"),
        (dict(latitude=2.44, longitude=-76.6, altitude=50.0), "INCOHERENT_FIELDS"),
    ],
)
def test_related_location_checks(ingested, f, loc, code):
    bad = ingested.model_copy(update={"related_locations": [
        ReportedLocation(role=LocationRole.CONTROL_STATION, **loc)]})
    assert ValidatorAgent().validate(bad, f.RECEIVED).reason_code == code


def test_unvalidated_observation_rejected(ingested, f):
    broken = Observation.model_construct(**{**ingested.observation.model_dump(), "latitude": 120.0})
    bad = IngestionResult.model_construct(observation=broken, related_locations=[], warnings=[])
    assert ValidatorAgent().validate(bad, f.RECEIVED).reason_code == "INVALID_OBSERVATION"


def test_simulated_flag_preserved(f):
    v = ValidatorAgent(KNOWN)
    agent = IngestionAgent()
    sim = v.validate(agent.ingest(f.rid_event()), f.RECEIVED)
    real = v.validate(agent.ingest(f.rid_event(payload=f.rid_payload(is_simulated=False))), f.RECEIVED)
    assert sim.observation.is_simulated is True and sim.observation.data_origin.value == "simulation"
    assert real.observation.is_simulated is False and real.observation.data_origin.value == "replay"


@pytest.mark.parametrize("garbage", [None, 1, "x", {}, [], object()])
def test_never_raises_on_garbage_result(garbage, f):
    res = ValidatorAgent(KNOWN).validate(garbage, f.RECEIVED)
    assert isinstance(res, RejectedInput) and res.stage == "validation"


@pytest.mark.parametrize("clock", [None, "2026-01-15", 0])
def test_never_raises_on_garbage_clock(ingested, clock):
    res = ValidatorAgent(KNOWN).validate(ingested, clock)
    assert isinstance(res, RejectedInput) and res.reason_code == "INVALID_CLOCK"


def test_result_timezone_utc(ingested, f):
    res = ValidatorAgent().validate(ingested, f.RECEIVED.astimezone(timezone(timedelta(hours=-5))))
    assert res.observation.timestamp_utc.tzinfo is not None
