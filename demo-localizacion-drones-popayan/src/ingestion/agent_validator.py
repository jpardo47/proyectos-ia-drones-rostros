"""Agente operativo de validación (``agent_validator``).

Segunda barrera tras la ingesta, con el reloj INYECTADO (``now_utc``): comprueba la
estación, la frescura del dato y la integridad de las ubicaciones asociadas.
Devuelve el ``IngestionResult`` (posiblemente con avisos añadidos) o
``RejectedInput(stage="validation")``. Nunca lanza excepciones.

Códigos: ``INVALID_INPUT``, ``INVALID_CLOCK``, ``INVALID_OBSERVATION``, ``UNKNOWN_STATION``,
``FUTURE_TIMESTAMP``, ``STALE``, ``OUT_OF_RANGE``, ``POSITION_SENTINEL``,
``INCOHERENT_FIELDS``, ``INTERNAL_ERROR``.

Como ``RejectedInput`` exige ``received_at_utc`` y aquí no se conoce la hora de
recepción, se registra ``now_utc`` (momento de la validación).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from src.contracts import IngestionResult, LocationRole, Observation, RejectedInput, ReportedLocation

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _aware(dt: object) -> bool:
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.utcoffset() is not None


class ValidatorAgent:
    name = "agent_validator"
    version = "1.0.0"

    def __init__(
        self,
        known_station_ids: Optional[Iterable[str]] = None,
        max_age_s: float = 120.0,
        max_future_s: float = 5.0,
    ) -> None:
        """``known_station_ids=None`` desactiva la comprobación de estación (un conjunto
        vacío, en cambio, rechaza todas). Tolerancias en segundos."""
        if max_age_s < 0 or max_future_s < 0:
            raise ValueError("las tolerancias de tiempo no pueden ser negativas")
        self.known_station_ids = None if known_station_ids is None else frozenset(known_station_ids)
        self.max_age_s = float(max_age_s)
        self.max_future_s = float(max_future_s)

    def validate(self, result: IngestionResult, now_utc: datetime) -> IngestionResult | RejectedInput:
        station_id: Optional[str] = None
        event_id: Optional[str] = None
        raw_ref: Optional[str] = None
        when = now_utc if isinstance(now_utc, datetime) else _EPOCH
        try:
            if not isinstance(result, IngestionResult):
                return self._reject(None, when, "INVALID_INPUT", f"se esperaba IngestionResult, se recibió {type(result).__name__}")
            obs = result.observation
            station_id = getattr(obs, "station_id", None)
            event_id = getattr(obs, "event_id", None)
            raw_ref = getattr(obs, "raw_reference", None)
            if not _aware(now_utc):
                return self._reject(station_id, when, "INVALID_CLOCK", "now_utc debe incluir zona horaria", raw_ref, event_id)
            now = now_utc.astimezone(timezone.utc)

            # Re-valida la observación: protege frente a objetos construidos sin validar.
            try:
                obs = Observation.model_validate(obs.model_dump())
            except (ValidationError, AttributeError) as exc:
                return self._reject(station_id, now, "INVALID_OBSERVATION",
                                    f"la observación no cumple el contrato ({type(exc).__name__})", raw_ref, event_id)

            if self.known_station_ids is not None and obs.station_id not in self.known_station_ids:
                return self._reject(station_id, now, "UNKNOWN_STATION",
                                    f"estación desconocida: {obs.station_id!r}", raw_ref, event_id)

            delta = (obs.timestamp_utc - now).total_seconds()
            if delta > self.max_future_s:
                return self._reject(station_id, now, "FUTURE_TIMESTAMP",
                                    f"observación fechada {delta:.1f} s en el futuro (tolerancia {self.max_future_s:g} s)",
                                    raw_ref, event_id)
            if -delta > self.max_age_s:
                return self._reject(station_id, now, "STALE",
                                    f"observación con {-delta:.1f} s de antigüedad (máximo {self.max_age_s:g} s)",
                                    raw_ref, event_id)

            if obs.has_position and obs.latitude == 0.0 and obs.longitude == 0.0:
                return self._reject(station_id, now, "POSITION_SENTINEL",
                                    "posición (0, 0): valor centinela de 'sin posición'", raw_ref, event_id)

            warnings = list(result.warnings)
            related: list[ReportedLocation] = []
            for loc in result.related_locations:
                loc = ReportedLocation.model_validate(loc.model_dump())
                problem = self._check_location(loc)
                if problem is not None:
                    code, reason = problem
                    return self._reject(station_id, now, code, reason, raw_ref, event_id)
                related.append(loc)
            if related and obs.sensor_type.value != "remote_id":
                warnings.append("ubicaciones asociadas en una observación que no es Remote ID")

            return IngestionResult(observation=obs, related_locations=related, warnings=warnings)
        except Exception as exc:  # red de seguridad
            return self._reject(station_id, when, "INTERNAL_ERROR",
                                f"error inesperado durante la validación ({type(exc).__name__})", raw_ref, event_id)

    @staticmethod
    def _check_location(loc: ReportedLocation) -> Optional[tuple[str, str]]:
        role = loc.role.value
        if loc.role == LocationRole.DRONE:
            return ("INCOHERENT_FIELDS",
                    "la posición del dron va en la observación, no en related_locations")
        for name, value, lo, hi in (("latitude", loc.latitude, -90.0, 90.0), ("longitude", loc.longitude, -180.0, 180.0)):
            if not math.isfinite(value) or value < lo or value > hi:
                return ("OUT_OF_RANGE", f"{role}.{name} fuera de rango")
        if loc.latitude == 0.0 and loc.longitude == 0.0:
            return ("POSITION_SENTINEL", f"{role} en (0, 0): valor centinela de 'sin posición'")
        if loc.altitude is not None:
            if not math.isfinite(loc.altitude) or not (-500.0 <= loc.altitude <= 20000.0):
                return ("OUT_OF_RANGE", f"{role}.altitude fuera de rango")
            if loc.altitude_reference is None:
                return ("INCOHERENT_FIELDS", f"{role}.altitude sin altitude_reference")
        return None

    @staticmethod
    def _reject(station_id, when, code, reason, raw_reference=None, event_id=None) -> RejectedInput:
        return RejectedInput(
            station_id=station_id if isinstance(station_id, str) else None,
            received_at_utc=when if isinstance(when, datetime) else _EPOCH,
            stage="validation",
            reason_code=code,
            reason=reason,
            raw_reference=raw_reference if isinstance(raw_reference, str) else None,
            event_id=event_id if isinstance(event_id, str) else None,
        )


__all__ = ["ValidatorAgent"]
