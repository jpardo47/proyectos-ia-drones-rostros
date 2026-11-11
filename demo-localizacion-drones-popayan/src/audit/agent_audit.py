"""agent_audit: registro de cada paso del pipeline como ``AuditEvent``.

IDs deterministas: ``AUD-`` + hash de (secuencia, instante, actor, acción, sujeto).
La secuencia es un contador interno del pipeline (mismo orden de entrada -> mismos IDs).
Exporta a JSONL (una línea JSON por evento, claves ordenadas).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from src.contracts import AuditEvent

AUDIT_VERSION = "1.0.0"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_jsonable(v) for v in value]
        return sorted(items, key=str) if isinstance(value, (set, frozenset)) else items
    if hasattr(value, "value") and not isinstance(value, (int, float, str, bool)):
        return value.value  # Enum
    return value


class AuditAgent:
    name = "agent_audit"
    version = AUDIT_VERSION

    def __init__(self, engine_version: str):
        self.engine_version = engine_version
        self._seq = 0
        self._pending: list[AuditEvent] = []
        self.history: list[AuditEvent] = []

    def record(
        self,
        timestamp_utc: datetime,
        actor: str,
        action: str,
        subject: str,
        details: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        self._seq += 1
        raw = f"{self._seq}|{timestamp_utc.isoformat()}|{actor}|{action}|{subject}"
        event = AuditEvent(
            audit_id="AUD-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
            timestamp_utc=timestamp_utc,
            actor=actor,
            action=action,
            subject=subject,
            details=_jsonable(details or {}),
            engine_version=self.engine_version,
        )
        self._pending.append(event)
        self.history.append(event)
        return event

    def drain(self) -> list[AuditEvent]:
        """Devuelve y vacía los eventos acumulados desde la última llamada."""
        out, self._pending = self._pending, []
        return out

    @staticmethod
    def to_jsonl(events: Iterable[AuditEvent]) -> str:
        return "".join(
            json.dumps(e.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
            for e in events
        )

    def export_jsonl(self, path: str | Path, events: Optional[Iterable[AuditEvent]] = None,
                     append: bool = False) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_jsonl(self.history if events is None else events)
        with p.open("a" if append else "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
        return p
