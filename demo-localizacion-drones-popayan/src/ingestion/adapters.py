"""Adaptadores de recepción.

- ``ReceiverAdapter``: interfaz ABSTRACTA para una futura fuente de recepción
  AUTORIZADA. Solo define el contrato; no abre radios, sockets, interfaces de
  captura ni dispositivos. Ver ``docs/adaptador-recepcion.md``.
- ``ReplayFileAdapter``: reproduce archivos JSONL de ejemplo y produce ``RawEvent``.
  Las líneas que no se pueden convertir en ``RawEvent`` se registran en
  ``self.rejected`` como ``RejectedInput`` (no se descartan en silencio ni lanzan).

Formato de cada línea JSONL (sobre)::

    {"kind": "remote_id" | "observation", "station_id": "CIV-01",
     "received_at_utc": "2026-01-15T15:00:00.500Z", "payload": {...}}

Líneas vacías y líneas que empiezan por ``#`` se ignoran.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from src.contracts import RawEvent, RejectedInput
from src.remote_id.parser import describe_validation_errors

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MAX_LINE_BYTES = 64 * 1024


def _reject_constant(token: str) -> None:
    raise ValueError(f"constante no finita: {token}")


@dataclass(frozen=True)
class ReceptionAuthorization:
    """Constancia de autorización exigida a cualquier adaptador de recepción real.

    No es un mecanismo de seguridad: documenta quién autorizó la recepción, para qué
    y hasta cuándo, de modo que quede en la auditoría.
    """

    reference: str            # número de permiso / acta / convenio
    authorized_by: str        # entidad responsable (no una persona identificable por el sistema)
    scope: str                # qué se puede recibir y dónde
    valid_until_utc: Optional[datetime] = None


class ReceiverAdapter(ABC):
    """Interfaz para fuentes de ``RawEvent`` de recepción AUTORIZADA.

    Una implementación concreta (fuera de esta demo) debe:
    - recibir solo emisiones de difusión pública destinadas a ser recibidas
      (p. ej. Remote ID broadcast), nunca comunicaciones privadas;
    - no transmitir, interferir ni suplantar señales;
    - marcar ``is_simulated``/``data_origin`` con verdad;
    - entregar el ``payload`` sin modificar y con ``received_at_utc`` con zona horaria.
    """

    name: str = "receiver_adapter"

    def __init__(self, authorization: ReceptionAuthorization) -> None:
        if not isinstance(authorization, ReceptionAuthorization) or not authorization.reference.strip():
            raise ValueError("un adaptador de recepción requiere una autorización documentada")
        self.authorization = authorization

    @abstractmethod
    def events(self) -> Iterator[RawEvent]:
        """Itera los eventos recibidos, en orden de ``received_at_utc``."""

    @abstractmethod
    def describe(self) -> dict:
        """Metadatos del adaptador para auditoría (tipo, alcance, autorización)."""

    def close(self) -> None:  # pragma: no cover - implementación opcional
        """Libera recursos. Por defecto no hace nada."""


class ReplayFileAdapter:
    """Reproduce un archivo JSONL de ejemplo. Determinista, sin red ni hardware.

    No hereda de ``ReceiverAdapter`` porque no recibe nada: solo lee un archivo local.
    Expone la misma interfaz (``events()``, ``describe()``).
    """

    name = "replay_file_adapter"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.rejected: list[RejectedInput] = []

    def describe(self) -> dict:
        return {"adapter": self.name, "source": str(self.path), "data_origin": "replay",
                "note": "archivo de ejemplo reproducido; no es captura en vivo"}

    def events(self) -> Iterator[RawEvent]:
        self.rejected = []
        with self.path.open("r", encoding="utf-8-sig", errors="replace") as fh:
            for line_no, line in enumerate(fh, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                event = self._parse_line(text, line_no)
                if event is not None:
                    yield event

    def _parse_line(self, text: str, line_no: int) -> Optional[RawEvent]:
        ref = f"{self.path.name}:{line_no}"
        if len(text.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
            self._reject(ref, "PAYLOAD_TOO_LARGE", f"línea {line_no} supera {MAX_LINE_BYTES} bytes")
            return None
        try:
            data = json.loads(text, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            self._reject(ref, "MALFORMED_JSON", f"línea {line_no}: JSON mal formado")
            return None
        if not isinstance(data, dict):
            self._reject(ref, "INVALID_EVENT", f"línea {line_no}: el sobre debe ser un objeto JSON")
            return None
        try:
            event = RawEvent.model_validate(data)
        except ValidationError as exc:
            station = data.get("station_id") if isinstance(data.get("station_id"), str) else None
            self._reject(ref, "INVALID_EVENT", f"línea {line_no}: sobre inválido: {describe_validation_errors(exc)}", station)
            return None
        return event

    def _reject(self, ref: str, code: str, reason: str, station_id: Optional[str] = None) -> None:
        self.rejected.append(
            RejectedInput(
                station_id=station_id[:64] if station_id else None,
                received_at_utc=_EPOCH,  # marcador: la línea no aportó una hora utilizable
                stage="ingestion",
                reason_code=code,
                reason=reason,
                raw_reference=ref[:512],
            )
        )


__all__ = ["ReceiverAdapter", "ReceptionAuthorization", "ReplayFileAdapter"]
