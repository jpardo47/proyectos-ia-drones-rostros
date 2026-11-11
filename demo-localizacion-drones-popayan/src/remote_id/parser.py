"""Parser del formato de ejemplo ``rid-demo-1`` (ver ``src/contracts/remote_id_wire.py``).

El formato se INSPIRA en las familias de mensajes de ASTM F3411 / OpenDroneID, pero
es JSON de demostración: no hay compatibilidad binaria ni universal con equipos reales.

Reglas del parser (estructura y tipos; los rangos y tiempos van en ``validation.py``):

- Acepta ``dict``, cadena JSON o ``bytes`` UTF-8 (con o sin BOM). También un
  ``RemoteIdWireMessage`` ya construido, que se re-valida.
- Tipado ESTRICTO: no se coercionan cadenas a números (``"2.4"``), ni ``1``/``"true"``
  a booleanos, ni números a fechas. El ``timestamp_utc`` debe ser una cadena ISO 8601.
- Rechaza valores no finitos (``NaN``, ``Infinity``), campos desconocidos, versiones
  de esquema ausentes o distintas de ``rid-demo-1`` y cargas mayores que
  ``MAX_PAYLOAD_BYTES``.
- Nunca deja escapar otra excepción que ``RemoteIdParseError``.

Códigos estables de ``RemoteIdParseError.reason_code``:
``UNSUPPORTED_INPUT_TYPE``, ``PAYLOAD_TOO_LARGE``, ``INVALID_ENCODING``,
``MALFORMED_JSON``, ``NOT_AN_OBJECT``, ``UNSUPPORTED_VERSION``, ``NON_FINITE_VALUE``,
``SCHEMA_ERROR``.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import ValidationError

from src.contracts import RID_WIRE_VERSION, RemoteIdWireMessage

#: Tamaño máximo aceptado de un mensaje serializado (bytes). Un mensaje real
#: ``rid-demo-1`` ocupa menos de 2 KiB; 64 KiB deja margen sin abrir la puerta a
#: cargas abusivas.
MAX_PAYLOAD_BYTES = 64 * 1024

SUPPORTED_VERSIONS = frozenset({RID_WIRE_VERSION})


class RemoteIdParseError(ValueError):
    """Error de parseo con código estable (``reason_code``) y motivo en español."""

    def __init__(self, reason_code: str, reason: str) -> None:
        super().__init__(f"{reason_code}: {reason}")
        self.reason_code = reason_code
        self.reason = reason


def _reject_constant(token: str) -> Any:
    raise RemoteIdParseError(
        "NON_FINITE_VALUE", f"valor numérico no finito no permitido en JSON: {token}"
    )


def _json_default(obj: Any) -> Any:
    """Permite dicts producidos con ``model_dump()`` (modo python)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"tipo no serializable: {type(obj).__name__}")


def _load_text(text: str) -> Any:
    if len(text.encode("utf-8", errors="surrogatepass")) > MAX_PAYLOAD_BYTES:
        raise RemoteIdParseError(
            "PAYLOAD_TOO_LARGE", f"el mensaje supera el máximo de {MAX_PAYLOAD_BYTES} bytes"
        )
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except RemoteIdParseError:
        raise
    except (ValueError, RecursionError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__
        raise RemoteIdParseError("MALFORMED_JSON", f"JSON mal formado ({detail})") from None


def describe_validation_errors(exc: ValidationError, limit: int = 5) -> str:
    parts = []
    for err in exc.errors(include_url=False)[:limit]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "(raíz)"
        etype = err.get("type", "")
        if etype == "missing":
            parts.append(f"falta el campo '{loc}'")
        elif etype == "extra_forbidden":
            parts.append(f"campo no permitido '{loc}'")
        else:
            parts.append(f"tipo o valor inválido en '{loc}' ({etype})")
    extra = len(exc.errors()) - limit
    if extra > 0:
        parts.append(f"y {extra} error(es) más")
    return "; ".join(parts)


def parse_remote_id(raw: dict | str | bytes) -> RemoteIdWireMessage:
    """Convierte ``raw`` en ``RemoteIdWireMessage`` o lanza ``RemoteIdParseError``."""
    try:
        return _parse(raw)
    except RemoteIdParseError:
        raise
    except Exception as exc:  # red de seguridad: nunca otra excepción
        raise RemoteIdParseError(
            "SCHEMA_ERROR", f"entrada no procesable ({type(exc).__name__})"
        ) from None


def _parse(raw: Any) -> RemoteIdWireMessage:
    if isinstance(raw, RemoteIdWireMessage):
        raw = raw.model_dump(mode="json")

    if isinstance(raw, (bytes, bytearray, memoryview)):
        data_bytes = bytes(raw)
        if len(data_bytes) > MAX_PAYLOAD_BYTES:
            raise RemoteIdParseError(
                "PAYLOAD_TOO_LARGE", f"el mensaje supera el máximo de {MAX_PAYLOAD_BYTES} bytes"
            )
        try:
            text = data_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise RemoteIdParseError("INVALID_ENCODING", "los bytes no son UTF-8 válido") from None
        data = _load_text(text)
    elif isinstance(raw, str):
        data = _load_text(raw)
    elif isinstance(raw, dict):
        data = raw
    else:
        raise RemoteIdParseError(
            "UNSUPPORTED_INPUT_TYPE",
            f"tipo de entrada no soportado: {type(raw).__name__} (se espera dict, str o bytes)",
        )

    if not isinstance(data, dict):
        raise RemoteIdParseError(
            "NOT_AN_OBJECT", f"el mensaje debe ser un objeto JSON, no {type(data).__name__}"
        )

    version = data.get("schema_version")
    if version is None:
        raise RemoteIdParseError(
            "UNSUPPORTED_VERSION", "falta 'schema_version'; se esperaba 'rid-demo-1'"
        )
    if not isinstance(version, str) or version not in SUPPORTED_VERSIONS:
        shown = version if isinstance(version, str) else type(version).__name__
        raise RemoteIdParseError(
            "UNSUPPORTED_VERSION",
            f"versión de esquema no soportada: {str(shown)[:40]!r}; se esperaba 'rid-demo-1'",
        )

    if "timestamp_utc" in data and not isinstance(data["timestamp_utc"], (str, datetime)):
        raise RemoteIdParseError(
            "SCHEMA_ERROR", "tipo o valor inválido en 'timestamp_utc' (se espera cadena ISO 8601)"
        )

    try:
        text = json.dumps(data, allow_nan=False, default=_json_default)
    except ValueError as exc:
        if "Circular" in str(exc):
            raise RemoteIdParseError("SCHEMA_ERROR", "estructura circular no permitida") from None
        raise RemoteIdParseError(
            "NON_FINITE_VALUE", "el mensaje contiene valores numéricos no finitos (NaN/Infinity)"
        ) from None
    except (TypeError, RecursionError) as exc:
        raise RemoteIdParseError(
            "SCHEMA_ERROR", f"el mensaje contiene valores no representables en JSON ({type(exc).__name__})"
        ) from None

    if len(text.encode("utf-8", errors="surrogatepass")) > MAX_PAYLOAD_BYTES:
        raise RemoteIdParseError(
            "PAYLOAD_TOO_LARGE", f"el mensaje supera el máximo de {MAX_PAYLOAD_BYTES} bytes"
        )

    try:
        return RemoteIdWireMessage.model_validate_json(text, strict=True)
    except ValidationError as exc:
        raise RemoteIdParseError("SCHEMA_ERROR", describe_validation_errors(exc)) from None
