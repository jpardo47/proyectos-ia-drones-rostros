import json
import math
from datetime import datetime, timezone

import pytest

from src.contracts import RemoteIdWireMessage
from src.remote_id import MAX_PAYLOAD_BYTES, RemoteIdParseError, parse_remote_id


def test_parses_dict_str_and_bytes(make_msg):
    raw = make_msg()
    from_dict = parse_remote_id(raw)
    from_str = parse_remote_id(json.dumps(raw))
    from_bytes = parse_remote_id(json.dumps(raw).encode("utf-8"))
    from_bom = parse_remote_id(b"\xef\xbb\xbf" + json.dumps(raw).encode("utf-8"))
    assert from_dict == from_str == from_bytes == from_bom
    assert isinstance(from_dict, RemoteIdWireMessage)
    assert from_dict.drone.latitude == 2.4452
    assert from_dict.timestamp_utc == datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)


def test_accepts_python_mode_model_dump(make_msg):
    msg = parse_remote_id(make_msg())
    assert parse_remote_id(msg.model_dump()) == msg
    assert parse_remote_id(msg) == msg


def test_parse_error_is_value_error_with_code_and_spanish_reason():
    with pytest.raises(ValueError) as info:
        parse_remote_id("{no es json")
    err = info.value
    assert isinstance(err, RemoteIdParseError)
    assert err.reason_code == "MALFORMED_JSON"
    assert "JSON mal formado" in err.reason


@pytest.mark.parametrize(
    "raw, code",
    [
        ("{", "MALFORMED_JSON"),
        ("", "MALFORMED_JSON"),
        ("[" * 60000, "MALFORMED_JSON"),  # anidamiento profundo (RecursionError controlado)
        ('{"schema_version": "rid-demo-1", "x": NaN}', "NON_FINITE_VALUE"),
        (b"\xff\xfe\x00garbage", "INVALID_ENCODING"),
        ("[1, 2, 3]", "NOT_AN_OBJECT"),
        ('"texto"', "NOT_AN_OBJECT"),
        ("null", "NOT_AN_OBJECT"),
        (12345, "UNSUPPORTED_INPUT_TYPE"),
        (None, "UNSUPPORTED_INPUT_TYPE"),
        (["lista"], "UNSUPPORTED_INPUT_TYPE"),
        ("x" * (MAX_PAYLOAD_BYTES + 1), "PAYLOAD_TOO_LARGE"),
        (b"x" * (MAX_PAYLOAD_BYTES + 1), "PAYLOAD_TOO_LARGE"),
    ],
)
def test_malformed_inputs(raw, code):
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(raw)
    assert info.value.reason_code == code


@pytest.mark.parametrize("version", ["rid-demo-2", "RID-DEMO-1", "", 1, None])
def test_unsupported_or_missing_version(make_msg, version):
    raw = make_msg()
    if version is None:
        raw.pop("schema_version")
    else:
        raw["schema_version"] = version
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(raw)
    assert info.value.reason_code == "UNSUPPORTED_VERSION"


@pytest.mark.parametrize(
    "overrides",
    [
        {"drone__latitude": "2.4452"},          # cadena en lugar de número
        {"drone__latitude": True},              # booleano en lugar de número
        {"is_simulated": "true"},               # cadena en lugar de booleano
        {"is_simulated": 1},                    # entero en lugar de booleano
        {"timestamp_utc": 1768489200},          # época numérica: no se acepta
        {"timestamp_utc": "ayer por la tarde"},
        {"message_id": ""},
        {"message_id": 42},
        {"id_type": "pasaporte"},               # enum desconocido
        {"drone__height_reference": "msl"},     # literal no permitido
        {"campo_inventado": 1},                 # campo extra
        {"drone": "2.44,-76.60"},
    ],
)
def test_wrong_types_rejected_as_schema_error(make_msg, overrides):
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(make_msg(**overrides))
    assert info.value.reason_code == "SCHEMA_ERROR"


@pytest.mark.parametrize("field", ["message_id", "timestamp_utc", "is_simulated"])
def test_missing_required_field(make_msg, field):
    raw = make_msg()
    raw.pop(field)
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(raw)
    assert info.value.reason_code == "SCHEMA_ERROR"
    assert field in info.value.reason


def test_missing_drone_latitude_is_schema_error(make_msg):
    raw = make_msg()
    raw["drone"].pop("latitude")
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(raw)
    assert "drone.latitude" in info.value.reason


def test_non_finite_in_dict(make_msg):
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(make_msg(drone__speed_mps=math.inf))
    assert info.value.reason_code == "NON_FINITE_VALUE"


def test_circular_dict_does_not_crash(make_msg):
    raw = make_msg()
    raw["drone"]["self"] = raw
    with pytest.raises(RemoteIdParseError) as info:
        parse_remote_id(raw)
    assert info.value.reason_code == "SCHEMA_ERROR"


def test_naive_timestamp_is_parsed_but_kept_naive(make_msg):
    msg = parse_remote_id(make_msg(timestamp_utc="2026-01-15T15:00:00"))
    assert msg.timestamp_utc.tzinfo is None  # la validación lo rechazará (TIMESTAMP_NO_TZ)
