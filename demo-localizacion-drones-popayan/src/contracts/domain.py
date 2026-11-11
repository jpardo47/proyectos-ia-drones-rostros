"""Tipos de dominio compartidos entre módulos del Proyecto 3.

Propietario: coordinador (Fable). Los subagentes los IMPORTAN, no los modifican.
Si un módulo necesita un campo nuevo, se pide en el informe; no se edita aquí.

Todo timestamp es ``datetime`` con zona horaria UTC.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .observation import AltitudeReference, Observation, SensorType

# --------------------------------------------------------------------------- #
# Estaciones
# --------------------------------------------------------------------------- #


class StationCategory(str, Enum):
    CIVIL_FICTICIA = "civil_ficticia"
    INSTITUCIONAL_ABSTRACTA = "institucional_abstracta"


class StationStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class Station(BaseModel):
    """Nodo FICTICIO de la simulación.

    - Estaciones ``civil_ficticia``: coordenadas inventadas por regla geométrica
      sobre la cartografía pública; no corresponden a equipos reales.
    - Nodos ``institucional_abstracta``: NO tienen ubicación geográfica
      (``latitude``/``longitude`` = ``None``). Son fuentes de datos lógicas; no
      representan posiciones, equipos, bases ni unidades reales.
    """

    model_config = ConfigDict(extra="forbid")

    station_id: str
    category: StationCategory
    name: str
    simulated_environment: str
    virtual_sensors: list[SensorType]
    status: StationStatus = StationStatus.ONLINE
    status_timestamp_utc: Optional[datetime] = None
    data_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    is_fictitious: Literal[True] = True
    notes: Optional[str] = None

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


# --------------------------------------------------------------------------- #
# Simulación (estado verdadero SEPARADO de lo observado)
# --------------------------------------------------------------------------- #


class TruthState(BaseModel):
    """Estado verdadero del escenario. Nunca entra al pipeline como observación."""

    model_config = ConfigDict(extra="forbid")
    drone_id: str
    timestamp_utc: datetime
    latitude: float
    longitude: float
    altitude_agl_m: float
    emits_remote_id: bool
    emits_sound: bool = True


class RawEvent(BaseModel):
    """Lo que una estación virtual 'recibe' y entrega a la ingesta.

    ``kind == "remote_id"``   -> ``payload`` es un JSON ``rid-demo-1``
                                 (ver ``remote_id_wire.RemoteIdWireMessage``);
                                 puede venir malformado a propósito.
    ``kind == "observation"`` -> ``payload`` es un JSON con forma de
                                 ``Observation`` (sensores no Remote ID);
                                 puede venir malformado a propósito.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["remote_id", "observation"]
    station_id: str
    received_at_utc: datetime
    payload: dict[str, Any]


class ScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    seed: int
    description: str
    start_utc: datetime
    end_utc: datetime
    stations: list[Station]
    truth: list[TruthState]
    raw_events: list[RawEvent]  # ordenados por received_at_utc
    is_simulated: Literal[True] = True


# --------------------------------------------------------------------------- #
# Ingesta y validación
# --------------------------------------------------------------------------- #


class LocationRole(str, Enum):
    DRONE = "drone"
    CONTROL_STATION = "control_station"
    TAKEOFF_POINT = "takeoff_point"


class ReportedLocation(BaseModel):
    """Ubicación REPORTADA (no verificada) con su rol explícito."""

    model_config = ConfigDict(extra="forbid")
    role: LocationRole
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    altitude_reference: Optional[AltitudeReference] = None
    detail: Optional[str] = None  # p. ej. "live_gnss", "fixed"


class IngestionResult(BaseModel):
    """Observación normalizada + ubicaciones asociadas que no caben en ella."""

    model_config = ConfigDict(extra="forbid")
    observation: Observation
    related_locations: list[ReportedLocation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RejectedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_id: Optional[str]
    received_at_utc: datetime
    stage: Literal["ingestion", "validation"]
    reason_code: str   # p. ej. "MALFORMED", "OUT_OF_RANGE", "STALE", "FUTURE_TIMESTAMP"
    reason: str        # explicación legible en español
    raw_reference: Optional[str] = None
    event_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Correlación, seguimiento, decisiones, alertas, auditoría
# --------------------------------------------------------------------------- #


class DetectionState(str, Enum):
    SIN_OBSERVACION = "SIN_OBSERVACION"
    DETECCION_POSIBLE = "DETECCION_POSIBLE"
    DETECCION_CORROBORADA = "DETECCION_CORROBORADA"
    REQUIERE_REVISION = "REQUIERE_REVISION"
    DESCARTADA = "DESCARTADA"
    SEGUIMIENTO_PERDIDO = "SEGUIMIENTO_PERDIDO"


class TrackPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp_utc: datetime
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    altitude_reference: Optional[AltitudeReference] = None
    uncertainty_m: Optional[float] = None
    source_event_ids: list[str] = Field(default_factory=list)


class Track(BaseModel):
    """Trayectoria de un objeto observado. ``points`` puede estar vacío
    (p. ej. un objeto detectado solo por audio no tiene posiciones)."""

    model_config = ConfigDict(extra="forbid")
    track_id: str
    object_id: Optional[str] = None
    points: list[TrackPoint] = Field(default_factory=list)
    first_seen_utc: datetime
    last_seen_utc: datetime
    station_ids: list[str] = Field(default_factory=list)
    sensor_types: list[SensorType] = Field(default_factory=list)
    is_lost: bool = False
    is_simulated: bool


class DecisionRecord(BaseModel):
    """Cambio (o confirmación) de estado, explicable y auditable."""

    model_config = ConfigDict(extra="forbid")
    decision_id: str
    track_id: str
    state: DetectionState
    previous_state: DetectionState
    rule_id: str                    # regla determinista que disparó la decisión
    reason: str                     # motivo legible en español
    evidence_event_ids: list[str] = Field(default_factory=list)
    requires_human_review: bool
    decided_at_utc: datetime
    engine_version: str
    is_simulated: bool


class ReviewStatus(str, Enum):
    PENDIENTE = "pendiente"
    CONFIRMADA = "confirmada"
    DESCARTADA = "descartada"


class Alert(BaseModel):
    """Alerta INFORMATIVA para revisión humana. No clasifica amenazas ni ordena acciones."""

    model_config = ConfigDict(extra="forbid")
    alert_id: str
    track_id: str
    state: DetectionState
    message: str
    severity: Literal["informativa"] = "informativa"
    requires_human_review: bool = True
    created_at_utc: datetime
    review_status: ReviewStatus = ReviewStatus.PENDIENTE
    reviewed_by: Optional[str] = None
    reviewed_at_utc: Optional[datetime] = None
    review_note: Optional[str] = None
    decision_id: Optional[str] = None
    is_simulated: bool


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: str
    timestamp_utc: datetime
    actor: str        # nombre del agente operativo o "operador:<usuario>"
    action: str
    subject: str      # event_id / track_id / alert_id / station_id
    details: dict[str, Any] = Field(default_factory=dict)
    engine_version: str


class PipelineResult(BaseModel):
    """Salida de ``OperationalPipeline.process_batch``. Solo incluye lo que
    cambió en ese lote, excepto ``tracks`` que es el estado completo vigente."""

    model_config = ConfigDict(extra="forbid")
    processed_at_utc: datetime
    accepted: list[Observation] = Field(default_factory=list)
    rejected: list[RejectedInput] = Field(default_factory=list)
    duplicates_dropped: list[str] = Field(default_factory=list)  # event_id
    tracks: list[Track] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
