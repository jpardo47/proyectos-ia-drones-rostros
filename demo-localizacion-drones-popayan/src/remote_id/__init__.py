"""Remote ID de ejemplo (``rid-demo-1``): parseo, validación y normalización.

Formato inspirado en ASTM F3411 / OpenDroneID; sin compatibilidad binaria ni universal.
"""
from .convert import make_event_id, make_raw_reference, select_altitude, to_ingestion_result
from .parser import MAX_PAYLOAD_BYTES, RemoteIdParseError, parse_remote_id
from .validation import (
    DEFAULT_LIMITS,
    RemoteIdLimits,
    ValidationIssue,
    check_remote_id,
    error_code,
    validate_remote_id,
)

__all__ = [
    "parse_remote_id", "RemoteIdParseError", "MAX_PAYLOAD_BYTES",
    "validate_remote_id", "check_remote_id", "RemoteIdLimits", "DEFAULT_LIMITS",
    "ValidationIssue", "error_code",
    "to_ingestion_result", "make_event_id", "make_raw_reference", "select_altitude",
]
