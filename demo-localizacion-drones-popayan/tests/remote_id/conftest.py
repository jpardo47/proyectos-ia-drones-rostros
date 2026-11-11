"""Fábricas deterministas de mensajes rid-demo-1 FICTICIOS (alrededor de 2.4419, -76.6063)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

T0 = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
RECEIVED = datetime(2026, 1, 15, 15, 0, 0, 500000, tzinfo=timezone.utc)

BASE_MESSAGE = {
    "schema_version": "rid-demo-1",
    "message_id": "test-msg-001",
    "timestamp_utc": "2026-01-15T15:00:00Z",
    "is_simulated": True,
    "uas_id": "SIM-UAS-0001",
    "id_type": "serial_number",
    "ua_type": "helicopter_or_multirotor",
    "drone": {
        "latitude": 2.4452, "longitude": -76.6021,
        "altitude_geodetic_m": 1795.0, "altitude_pressure_m": 1792.5,
        "height_agl_m": 55.0, "height_reference": "takeoff",
        "horizontal_accuracy_m": 3.0, "vertical_accuracy_m": 4.5,
        "speed_mps": 6.2, "track_deg": 135.0,
    },
    "operator": {"latitude": 2.4431, "longitude": -76.6049, "altitude_geodetic_m": 1741.0, "location_kind": "live_gnss"},
    "takeoff": {"latitude": 2.4433, "longitude": -76.6047, "altitude_geodetic_m": 1740.0},
    "operator_id": "OP-FICTICIO-000",
}


def make_message(**overrides) -> dict:
    """Copia de BASE_MESSAGE; ``campo=None`` borra; ``drone__latitude=x`` toca subcampos."""
    msg = copy.deepcopy(BASE_MESSAGE)
    for key, value in overrides.items():
        if "__" in key:
            parent, child = key.split("__", 1)
            msg[parent][child] = value
        elif value is None:
            msg.pop(key, None)
        else:
            msg[key] = value
    return msg


@pytest.fixture
def make_msg():
    return make_message
