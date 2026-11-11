"""Contratos compartidos del Proyecto 3 (propiedad del coordinador)."""
from .domain import (
    Alert,
    AuditEvent,
    DecisionRecord,
    DetectionState,
    IngestionResult,
    LocationRole,
    PipelineResult,
    RawEvent,
    RejectedInput,
    ReportedLocation,
    ReviewStatus,
    ScenarioResult,
    Station,
    StationCategory,
    StationStatus,
    Track,
    TrackPoint,
    TruthState,
)
from .observation import (
    CONTRACT_VERSION,
    AltitudeReference,
    DataOrigin,
    Observation,
    SensorType,
)
from .remote_id_wire import (
    RID_WIRE_VERSION,
    RemoteIdWireMessage,
    RidDronePosition,
    RidIdType,
    RidOperatorLocation,
    RidOperatorLocationKind,
    RidTakeoffPoint,
)
from .stations_default import POPAYAN_REFERENCE, load_default_stations

__all__ = [
    "Alert", "AuditEvent", "DecisionRecord", "DetectionState", "IngestionResult",
    "LocationRole", "PipelineResult", "RawEvent", "RejectedInput", "ReportedLocation",
    "ReviewStatus", "ScenarioResult", "Station", "StationCategory", "StationStatus",
    "Track", "TrackPoint", "TruthState",
    "CONTRACT_VERSION", "AltitudeReference", "DataOrigin", "Observation", "SensorType",
    "RID_WIRE_VERSION", "RemoteIdWireMessage", "RidDronePosition", "RidIdType",
    "RidOperatorLocation", "RidOperatorLocationKind", "RidTakeoffPoint",
    "POPAYAN_REFERENCE", "load_default_stations",
]
