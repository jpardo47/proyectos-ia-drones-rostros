"""Contrato compartido de observación (v1.0.0).

Propietario: coordinador (Fable). Los subagentes lo IMPORTAN, no lo modifican.
Espejo JSON Schema: ``contracts/observation.schema.json`` (raíz del repositorio).

Reglas de integridad que el contrato hace cumplir:
- ``timestamp_utc`` debe llevar zona horaria; se normaliza a UTC.
- ``latitude`` y ``longitude`` van juntas o ambas ``None``.
- ``altitude`` exige ``altitude_reference`` (puede ser ``unknown``).
- ``data_origin == simulation``  <=>  ``is_simulated is True``.
- Una observación ``acoustic`` NO puede llevar coordenadas ni altitud:
  una clasificación de audio no produce por sí sola una posición.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0.0"


class SensorType(str, Enum):
    REMOTE_ID = "remote_id"
    ACOUSTIC = "acoustic"
    RF = "rf"
    OPTICAL = "optical"
    RADAR = "radar"
    MANUAL = "manual"


class DataOrigin(str, Enum):
    SIMULATION = "simulation"  # generado por el simulador
    REPLAY = "replay"          # archivo de ejemplo reproducido (no es captura en vivo)
    SENSOR = "sensor"          # sensor físico autorizado (no existe en esta demo)
    MANUAL = "manual"          # ingresado por un operador humano


class AltitudeReference(str, Enum):
    AGL = "agl"
    MSL = "msl"
    WGS84 = "wgs84"
    TAKEOFF = "takeoff"
    UNKNOWN = "unknown"


class Observation(BaseModel):
    """Observación normalizada de un sensor (real o virtual). 16 campos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    station_id: str = Field(min_length=1, max_length=64)
    sensor_type: SensorType
    timestamp_utc: datetime
    data_origin: DataOrigin
    is_simulated: bool
    object_id: Optional[str] = Field(default=None, max_length=128)
    classification: Optional[str] = Field(default=None, max_length=64)
    classifier_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    altitude: Optional[float] = Field(default=None, ge=-500.0, le=20000.0)  # metros
    altitude_reference: Optional[AltitudeReference] = None
    measurement_uncertainty: Optional[float] = Field(default=None, ge=0.0)  # metros, horizontal 1-sigma
    sensor_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    raw_reference: Optional[str] = Field(default=None, max_length=512)

    @field_validator("timestamp_utc")
    @classmethod
    def _tz_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc debe incluir zona horaria (UTC)")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _consistency(self) -> "Observation":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude y longitude deben ir juntas o ambas nulas")
        if self.altitude is not None and self.altitude_reference is None:
            raise ValueError("altitude requiere altitude_reference (use 'unknown' si no se conoce)")
        if (self.data_origin == DataOrigin.SIMULATION) != self.is_simulated:
            raise ValueError("is_simulated debe ser True si y solo si data_origin == 'simulation'")
        if self.sensor_type == SensorType.ACOUSTIC and (
            self.latitude is not None or self.altitude is not None
        ):
            raise ValueError("una observación acústica no puede llevar coordenadas ni altitud")
        return self

    @property
    def has_position(self) -> bool:
        return self.latitude is not None and self.longitude is not None
