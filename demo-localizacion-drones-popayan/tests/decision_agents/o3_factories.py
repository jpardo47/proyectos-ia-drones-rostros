"""Fábricas de observaciones construidas a mano para los tests de O3 (sin simulador)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.contracts import AltitudeReference, DataOrigin, Observation, SensorType

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
# Punto ficticio de referencia (zona urbana genérica de Popayán, sin significado especial).
LAT0, LON0 = 2.4440, -76.6060


def t(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def offset(lat: float, lon: float, north_m: float = 0.0, east_m: float = 0.0) -> tuple[float, float]:
    """Desplazamiento aproximado en metros (suficiente para tests)."""
    import math

    dlat = north_m / 111_320.0
    dlon = east_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def obs(
    event_id: str,
    sensor: SensorType = SensorType.REMOTE_ID,
    station: str = "EST-SIM-01",
    at: float = 0.0,
    object_id: Optional[str] = "UAS-SIM-0001",
    pos: Optional[tuple[float, float]] = (LAT0, LON0),
    uncertainty: Optional[float] = 10.0,
    quality: Optional[float] = 0.9,
    score: Optional[float] = None,
    simulated: bool = True,
    altitude: Optional[float] = None,
) -> Observation:
    lat, lon = (pos if pos is not None else (None, None))
    if sensor == SensorType.ACOUSTIC:
        lat = lon = None
        altitude = None
    return Observation(
        event_id=event_id,
        station_id=station,
        sensor_type=sensor,
        timestamp_utc=t(at),
        data_origin=DataOrigin.SIMULATION if simulated else DataOrigin.REPLAY,
        is_simulated=simulated,
        object_id=object_id,
        classification="drone" if score is not None else None,
        classifier_score=score,
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        altitude_reference=AltitudeReference.AGL if altitude is not None else None,
        measurement_uncertainty=uncertainty if lat is not None else None,
        sensor_quality=quality,
    )
