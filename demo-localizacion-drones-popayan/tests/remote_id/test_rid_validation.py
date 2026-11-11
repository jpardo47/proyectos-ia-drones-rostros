from datetime import datetime, timedelta, timezone

import pytest

from src.contracts import RemoteIdWireMessage
from src.remote_id import (
    RemoteIdLimits,
    check_remote_id,
    error_code,
    parse_remote_id,
    validate_remote_id,
)

T0 = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
RECEIVED = T0 + timedelta(milliseconds=500)



def codes(errors):
    return [error_code(e) for e in errors]


def test_valid_message_has_no_errors(make_msg):
    assert validate_remote_id(parse_remote_id(make_msg()), RECEIVED) == []


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"drone__latitude": 90.0001}, "drone.latitude"),
        ({"drone__latitude": -91.0}, "drone.latitude"),
        ({"drone__longitude": 180.5}, "drone.longitude"),
        ({"drone__longitude": -200.0}, "drone.longitude"),
        ({"drone__altitude_geodetic_m": 15000.0}, "drone.altitude_geodetic_m"),
        ({"drone__altitude_pressure_m": -900.0}, "drone.altitude_pressure_m"),
        ({"drone__height_agl_m": 5000.0}, "drone.height_agl_m"),
        ({"drone__height_agl_m": -150.0}, "drone.height_agl_m"),
        ({"drone__horizontal_accuracy_m": -1.0}, "drone.horizontal_accuracy_m"),
        ({"drone__vertical_accuracy_m": -0.1}, "drone.vertical_accuracy_m"),
        ({"drone__speed_mps": -0.5}, "drone.speed_mps"),
        ({"drone__speed_mps": 150.0}, "drone.speed_mps"),
        ({"drone__track_deg": -1.0}, "drone.track_deg"),
        ({"drone__track_deg": 360.1}, "drone.track_deg"),
        ({"operator__latitude": 120.0}, "operator.latitude"),
        ({"takeoff__longitude": 181.0}, "takeoff.longitude"),
        ({"operator__altitude_geodetic_m": 99999.0}, "operator.altitude_geodetic_m"),
    ],
)
def test_out_of_range(make_msg, overrides, field):
    errors = validate_remote_id(parse_remote_id(make_msg(**overrides)), RECEIVED)
    assert codes(errors) == ["OUT_OF_RANGE"]
    assert field in errors[0]


@pytest.mark.parametrize("lat, lon", [(90.0, 180.0), (-90.0, -180.0), (0.0, -76.6)])
def test_boundaries_accepted(make_msg, lat, lon):
    msg = parse_remote_id(make_msg(drone__latitude=lat, drone__longitude=lon))
    assert validate_remote_id(msg, RECEIVED) == []


@pytest.mark.parametrize("track", [0.0, 359.9, 360.0])
def test_track_bounds(make_msg, track):
    assert validate_remote_id(parse_remote_id(make_msg(drone__track_deg=track)), RECEIVED) == []


@pytest.mark.parametrize("part", ["drone", "operator", "takeoff"])
def test_null_island_sentinel(make_msg, part):
    msg = parse_remote_id(make_msg(**{f"{part}__latitude": 0.0, f"{part}__longitude": 0.0}))
    assert codes(validate_remote_id(msg, RECEIVED)) == ["POSITION_SENTINEL"]


def test_non_finite_value_from_constructed_model(make_msg):
    msg = parse_remote_id(make_msg())
    bad = msg.model_copy(update={"drone": msg.drone.model_copy(update={"latitude": float("nan")})})
    assert "NON_FINITE_VALUE" in codes(validate_remote_id(bad, RECEIVED))


def test_future_timestamp(make_msg):
    msg = parse_remote_id(make_msg())
    assert codes(validate_remote_id(msg, T0 - timedelta(seconds=6))) == ["FUTURE_TIMESTAMP"]
    assert validate_remote_id(msg, T0 - timedelta(seconds=5)) == []  # dentro de la tolerancia


def test_stale_timestamp(make_msg):
    msg = parse_remote_id(make_msg())
    assert codes(validate_remote_id(msg, T0 + timedelta(seconds=121))) == ["STALE"]
    assert validate_remote_id(msg, T0 + timedelta(seconds=120)) == []


def test_tolerances_are_parameters(make_msg):
    msg = parse_remote_id(make_msg())
    late = T0 + timedelta(seconds=90)
    assert validate_remote_id(msg, late) == []
    assert codes(validate_remote_id(msg, late, max_age_s=60)) == ["STALE"]
    assert codes(validate_remote_id(msg, late, RemoteIdLimits(max_age_s=30))) == ["STALE"]


def test_timestamp_without_zone(make_msg):
    msg = parse_remote_id(make_msg(timestamp_utc="2026-01-15T15:00:00"))
    assert codes(validate_remote_id(msg, RECEIVED)) == ["TIMESTAMP_NO_TZ"]


def test_timestamp_with_offset_is_normalized_comparison(make_msg):
    msg = parse_remote_id(make_msg(timestamp_utc="2026-01-15T10:00:00-05:00"))  # = 15:00Z
    assert validate_remote_id(msg, RECEIVED) == []


def test_received_at_without_zone(make_msg):
    msg = parse_remote_id(make_msg())
    assert codes(validate_remote_id(msg, datetime(2026, 1, 15, 15, 0, 1))) == ["INVALID_RECEIVED_AT"]


def test_height_without_reference_is_incoherent(make_msg):
    msg = parse_remote_id(make_msg(drone__height_reference=None))
    assert codes(validate_remote_id(msg, RECEIVED)) == ["INCOHERENT_FIELDS"]


def test_height_reference_without_value_is_only_warning(make_msg):
    msg = parse_remote_id(make_msg(drone__height_agl_m=None))
    assert validate_remote_id(msg, RECEIVED) == []
    warnings = [i for i in check_remote_id(msg, RECEIVED) if i.severity == "warning"]
    assert any(i.code == "HEIGHT_REFERENCE_WITHOUT_VALUE" for i in warnings)


@pytest.mark.parametrize("overrides", [{"uas_id": "   "}, {"uas_id": "U" * 129}, {"message_id": "M" * 129}])
def test_invalid_identifiers(make_msg, overrides):
    msg = parse_remote_id(make_msg(**overrides))
    assert codes(validate_remote_id(msg, RECEIVED)) == ["INVALID_FIELD"]


def test_reports_all_errors(make_msg):
    msg = parse_remote_id(make_msg(drone__speed_mps=-1.0, drone__track_deg=400.0, timestamp_utc="2026-01-15T15:10:00Z"))
    assert sorted(codes(validate_remote_id(msg, RECEIVED))) == ["FUTURE_TIMESTAMP", "OUT_OF_RANGE", "OUT_OF_RANGE"]


def test_missing_parts_are_not_errors(make_msg):
    msg = parse_remote_id(make_msg(drone=None, operator=None, takeoff=None, uas_id=None))
    assert validate_remote_id(msg, RECEIVED) == []


def test_validation_is_deterministic(make_msg):
    msg = parse_remote_id(make_msg(drone__speed_mps=-1.0))
    assert validate_remote_id(msg, RECEIVED) == validate_remote_id(msg, RECEIVED)
    assert isinstance(msg, RemoteIdWireMessage)
    assert RECEIVED.tzinfo is timezone.utc
