"""Fábricas deterministas para las pruebas de ingesta (datos FICTICIOS)."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from src.contracts import RawEvent

T0 = datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
RECEIVED = T0 + timedelta(milliseconds=500)

_RID = {
    "schema_version": "rid-demo-1",
    "message_id": "ing-msg-001",
    "timestamp_utc": "2026-01-15T15:00:00Z",
    "is_simulated": True,
    "uas_id": "SIM-UAS-0002",
    "id_type": "serial_number",
    "drone": {"latitude": 2.4452, "longitude": -76.6021, "altitude_geodetic_m": 1795.0,
              "horizontal_accuracy_m": 3.0, "speed_mps": 5.0, "track_deg": 90.0},
    "operator": {"latitude": 2.4431, "longitude": -76.6049, "location_kind": "fixed"},
    "takeoff": {"latitude": 2.4433, "longitude": -76.6047},
}

_OBS = {
    "event_id": "obs-ac-001",
    "station_id": "CIV-02",
    "sensor_type": "acoustic",
    "timestamp_utc": "2026-01-15T15:00:00Z",
    "data_origin": "simulation",
    "is_simulated": True,
    "classification": "drone",
    "classifier_score": 0.8,
}


def rid_payload(**overrides) -> dict:
    msg = copy.deepcopy(_RID)
    for key, value in overrides.items():
        if "__" in key:
            parent, child = key.split("__", 1)
            msg[parent][child] = value
        elif value is None:
            msg.pop(key, None)
        else:
            msg[key] = value
    return msg


def obs_payload(**overrides) -> dict:
    obs = copy.deepcopy(_OBS)
    for key, value in overrides.items():
        if value is None:
            obs.pop(key, None)
        else:
            obs[key] = value
    return obs


def rid_event(payload=None, station="CIV-01", received=RECEIVED) -> RawEvent:
    return RawEvent(kind="remote_id", station_id=station, received_at_utc=received,
                    payload=rid_payload() if payload is None else payload)


def obs_event(payload=None, station="CIV-02", received=RECEIVED) -> RawEvent:
    return RawEvent(kind="observation", station_id=station, received_at_utc=received,
                    payload=obs_payload() if payload is None else payload)


@pytest.fixture
def f():
    """Acceso a las fábricas y constantes desde las pruebas."""
    class _F:
        pass
    ns = _F()
    ns.T0, ns.RECEIVED = T0, RECEIVED
    ns.rid_payload, ns.obs_payload = rid_payload, obs_payload
    ns.rid_event, ns.obs_event = rid_event, obs_event
    return ns
