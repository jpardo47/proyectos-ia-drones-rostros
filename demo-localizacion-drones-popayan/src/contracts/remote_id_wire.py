"""Formato de intercambio (JSON) de mensajes Remote ID de EJEMPLO: ``rid-demo-1``.

Propietario: coordinador (Fable). Es el formato que el simulador EMITE y que
``src/remote_id`` PARSEA. Agrupa campos al estilo de las familias de mensajes de
ASTM F3411 / OpenDroneID (Basic ID, Location/Vector, System, Operator ID), pero
NO es una implementación binaria ni promete compatibilidad con equipos reales.

Tres ubicaciones distintas, nunca intercambiables:
- ``drone``    : posición reportada de la aeronave.
- ``operator`` : ubicación reportada de la estación de control (puede faltar).
- ``takeoff``  : punto de despegue reportado (puede faltar).
``None`` significa DESCONOCIDO; jamás se rellena ni se deduce.
``operator_id`` es un identificador administrativo: no se usa para deducir la
identidad de ninguna persona.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RID_WIRE_VERSION = "rid-demo-1"


class RidIdType(str, Enum):
    SERIAL_NUMBER = "serial_number"
    CAA_REGISTRATION = "caa_registration"
    UTM_UUID = "utm_uuid"
    SPECIFIC_SESSION = "specific_session"
    NONE = "none"


class RidOperatorLocationKind(str, Enum):
    LIVE_GNSS = "live_gnss"
    FIXED = "fixed"
    UNKNOWN = "unknown"


class RidDronePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float
    longitude: float
    altitude_geodetic_m: Optional[float] = None   # WGS84
    altitude_pressure_m: Optional[float] = None   # MSL barométrica
    height_agl_m: Optional[float] = None          # sobre el terreno / despegue
    height_reference: Optional[Literal["agl", "takeoff"]] = None
    horizontal_accuracy_m: Optional[float] = None
    vertical_accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None
    track_deg: Optional[float] = None


class RidOperatorLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float
    longitude: float
    altitude_geodetic_m: Optional[float] = None
    location_kind: RidOperatorLocationKind = RidOperatorLocationKind.UNKNOWN


class RidTakeoffPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float
    longitude: float
    altitude_geodetic_m: Optional[float] = None


class RemoteIdWireMessage(BaseModel):
    """Mensaje Remote ID de ejemplo tal como viaja en JSON.

    Este modelo es deliberadamente permisivo en rangos: la validación estricta
    (rangos, timestamps, coherencia) es responsabilidad de ``src/remote_id``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rid-demo-1"] = RID_WIRE_VERSION
    message_id: str = Field(min_length=1)
    timestamp_utc: datetime
    is_simulated: bool
    uas_id: Optional[str] = None
    id_type: RidIdType = RidIdType.NONE
    ua_type: Optional[str] = None
    drone: Optional[RidDronePosition] = None
    operator: Optional[RidOperatorLocation] = None
    takeoff: Optional[RidTakeoffPoint] = None
    operator_id: Optional[str] = None
