"""Agente operativo de ingesta (``agent_ingestion``).

Recibe ``RawEvent`` y devuelve ``IngestionResult`` o ``RejectedInput(stage="ingestion")``.
NUNCA lanza excepciones ante entrada malformada: cualquier fallo inesperado se
convierte en ``RejectedInput`` con ``reason_code="INTERNAL_ERROR"``.

- ``kind="remote_id"``: ``parse_remote_id`` -> ``validate_remote_id`` -> ``to_ingestion_result``.
- ``kind="observation"``: el ``payload`` se valida contra el contrato ``Observation`` con
  tipado estricto (sin coerciones de cadenas a números) más comprobaciones explícitas:
  acústico con coordenadas, incoherencia simulado/real, ``station_id`` distinto del del
  evento, posición centinela (0, 0) y valores no finitos.

Distinción simulado/real: se conserva tal como la declara el mensaje. Si el agente se
construye con ``expect_simulated`` (``True``/``False``) y un mensaje declara lo contrario,
se RECHAZA con ``SIMULATION_FLAG_MISMATCH``: un dato del simulador nunca puede pasar
por real, ni viceversa.

Códigos propios (además de los de ``parser`` y ``validation``): ``INVALID_EVENT``,
``INVALID_RECEIVED_AT``, ``UNSUPPORTED_KIND``, ``SIMULATION_FLAG_MISMATCH``,
``STATION_MISMATCH``, ``ACOUSTIC_WITH_POSITION``, ``INTERNAL_ERROR``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from src.contracts import (
    DataOrigin,
    IngestionResult,
    Observation,
    RawEvent,
    RejectedInput,
)
from src.remote_id.convert import make_event_id, make_raw_reference, to_ingestion_result
from src.remote_id.parser import RemoteIdParseError, describe_validation_errors, parse_remote_id
from src.remote_id.validation import DEFAULT_LIMITS, RemoteIdLimits, error_code, validate_remote_id

#: Hora usada en ``RejectedInput`` cuando la entrada ni siquiera trae una hora de
#: recepción válida (el contrato exige un ``datetime``). Es un marcador, no un dato.
UNKNOWN_RECEIVED_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)

_REAL_ORIGINS = (DataOrigin.REPLAY, DataOrigin.SENSOR, DataOrigin.MANUAL)


def _aware(dt: Any) -> bool:
    return isinstance(dt, datetime) and dt.tzinfo is not None and dt.utcoffset() is not None


def _short_str(value: Any, limit: int) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value[:limit]
    return None


class IngestionAgent:
    name = "agent_ingestion"
    version = "1.0.0"

    def __init__(
        self,
        real_data_origin: DataOrigin = DataOrigin.REPLAY,
        expect_simulated: Optional[bool] = None,
        limits: Optional[RemoteIdLimits] = None,
    ) -> None:
        """
        real_data_origin: origen asignado a mensajes Remote ID con ``is_simulated=false``
            (``replay`` por defecto: en esta demo no hay sensores físicos).
        expect_simulated: si se indica, los mensajes con la marca contraria se rechazan.
        limits: tolerancias de ``validate_remote_id`` (por defecto ``DEFAULT_LIMITS``).
        """
        real_data_origin = DataOrigin(real_data_origin)
        if real_data_origin not in _REAL_ORIGINS:
            raise ValueError("real_data_origin debe ser replay, sensor o manual")
        self.real_data_origin = real_data_origin
        self.expect_simulated = expect_simulated
        self.limits = limits or DEFAULT_LIMITS

    # ------------------------------------------------------------------ #
    def ingest(self, event: RawEvent) -> IngestionResult | RejectedInput:
        station_id: Optional[str] = None
        received_at: datetime = UNKNOWN_RECEIVED_AT
        try:
            if isinstance(event, dict):
                try:
                    event = RawEvent.model_validate(event)
                except ValidationError as exc:
                    return self._reject(
                        _short_str(event.get("station_id"), 64), UNKNOWN_RECEIVED_AT,
                        "INVALID_EVENT", "evento crudo inválido: " + describe_validation_errors(exc),
                    )
            if not isinstance(event, RawEvent):
                return self._reject(
                    None, UNKNOWN_RECEIVED_AT, "INVALID_EVENT",
                    f"se esperaba un RawEvent, se recibió {type(event).__name__}",
                )
            station_id = _short_str(getattr(event, "station_id", None), 64)
            raw_received = getattr(event, "received_at_utc", None)
            if isinstance(raw_received, datetime):
                received_at = raw_received
            if station_id is None:
                return self._reject(None, received_at, "INVALID_EVENT", "el evento no trae station_id válido")
            if len(event.station_id) > 64:
                return self._reject(station_id, received_at, "INVALID_EVENT", "station_id supera 64 caracteres")
            if not _aware(raw_received):
                return self._reject(
                    station_id, received_at, "INVALID_RECEIVED_AT",
                    "la hora de recepción del evento falta o no incluye zona horaria",
                )
            received_at = raw_received.astimezone(timezone.utc)

            kind = getattr(event, "kind", None)
            if kind == "remote_id":
                return self._ingest_remote_id(event.payload, station_id, received_at)
            if kind == "observation":
                return self._ingest_observation(event.payload, station_id, received_at)
            return self._reject(station_id, received_at, "UNSUPPORTED_KIND", f"tipo de evento no soportado: {str(kind)[:40]!r}")
        except Exception as exc:  # red de seguridad: el agente nunca lanza
            return self._reject(
                station_id, received_at, "INTERNAL_ERROR",
                f"error inesperado durante la ingesta ({type(exc).__name__})",
            )

    # ------------------------------------------------------------------ #
    def _ingest_remote_id(self, payload: Any, station_id: str, received_at: datetime) -> IngestionResult | RejectedInput:
        message_id = _short_str(payload.get("message_id"), 128) if isinstance(payload, dict) else None
        event_id = make_event_id(station_id, message_id) if message_id else None
        raw_ref = make_raw_reference(station_id, message_id) if message_id else None

        try:
            msg = parse_remote_id(payload)
        except RemoteIdParseError as exc:
            return self._reject(station_id, received_at, exc.reason_code, exc.reason, raw_ref, event_id)

        if self.expect_simulated is not None and msg.is_simulated != self.expect_simulated:
            return self._reject(
                station_id, received_at, "SIMULATION_FLAG_MISMATCH",
                f"el mensaje declara is_simulated={str(msg.is_simulated).lower()} "
                f"pero esta fuente es {'simulada' if self.expect_simulated else 'no simulada'}",
                raw_ref, event_id,
            )

        errors = validate_remote_id(msg, received_at, self.limits)
        if errors:
            return self._reject(
                station_id, received_at, error_code(errors[0]), "; ".join(errors)[:2000], raw_ref, event_id,
            )
        try:
            return to_ingestion_result(
                msg, station_id, received_at, data_origin=self.real_data_origin, limits=self.limits
            )
        except (ValueError, ValidationError) as exc:
            return self._reject(
                station_id, received_at, "SCHEMA_ERROR",
                f"no se pudo normalizar el mensaje: {str(exc)[:300]}", raw_ref, event_id,
            )

    # ------------------------------------------------------------------ #
    def _ingest_observation(self, payload: Any, station_id: str, received_at: datetime) -> IngestionResult | RejectedInput:
        if not isinstance(payload, dict):
            return self._reject(station_id, received_at, "NOT_AN_OBJECT", "el payload de la observación no es un objeto")
        event_id = _short_str(payload.get("event_id"), 128)
        raw_ref = _short_str(payload.get("raw_reference"), 512)

        def reject(code: str, reason: str) -> RejectedInput:
            return self._reject(station_id, received_at, code, reason, raw_ref, event_id)

        try:
            text = json.dumps(payload, allow_nan=False)
        except ValueError:
            return reject("NON_FINITE_VALUE", "la observación contiene valores no finitos (NaN/Infinity)")
        except (TypeError, RecursionError):
            return reject("SCHEMA_ERROR", "la observación contiene valores no representables en JSON")

        # Comprobaciones explícitas con códigos específicos (antes del modelo).
        sensor = payload.get("sensor_type")
        if sensor == "acoustic" and any(payload.get(k) is not None for k in ("latitude", "longitude", "altitude")):
            return reject(
                "ACOUSTIC_WITH_POSITION",
                "una observación acústica no puede llevar coordenadas ni altitud: el audio no produce posición",
            )
        origin, is_sim = payload.get("data_origin"), payload.get("is_simulated")
        if isinstance(is_sim, bool) and isinstance(origin, str) and (origin == "simulation") != is_sim:
            return reject(
                "SIMULATION_FLAG_MISMATCH",
                f"incoherencia: data_origin={origin!r} con is_simulated={str(is_sim).lower()}",
            )
        if isinstance(is_sim, bool) and self.expect_simulated is not None and is_sim != self.expect_simulated:
            return reject(
                "SIMULATION_FLAG_MISMATCH",
                f"la observación declara is_simulated={str(is_sim).lower()} "
                f"pero esta fuente es {'simulada' if self.expect_simulated else 'no simulada'}",
            )
        obs_station = payload.get("station_id")
        if isinstance(obs_station, str) and obs_station != station_id:
            return reject(
                "STATION_MISMATCH",
                f"la observación dice venir de {obs_station[:64]!r} pero el evento llegó por {station_id!r}",
            )
        ts = payload.get("timestamp_utc")
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return reject("TIMESTAMP_NO_TZ", "el timestamp de la observación no incluye zona horaria")
            except ValueError:
                pass  # lo reporta el modelo como SCHEMA_ERROR

        try:
            obs = Observation.model_validate_json(text, strict=True)
        except ValidationError as exc:
            return reject("SCHEMA_ERROR", "observación no conforme al contrato: " + describe_validation_errors(exc))

        warnings: list[str] = []
        if obs.has_position:
            if obs.latitude == 0.0 and obs.longitude == 0.0:
                return reject("POSITION_SENTINEL", "posición (0, 0): valor centinela de 'sin posición'")
        if obs.sensor_type.value == "remote_id":
            warnings.append("observación Remote ID recibida como observación genérica (sin related_locations)")
        if obs.sensor_type.value == "acoustic":
            warnings.append("observación acústica: sin coordenadas por diseño")
        return IngestionResult(observation=obs, related_locations=[], warnings=warnings)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _reject(
        station_id: Optional[str],
        received_at: datetime,
        code: str,
        reason: str,
        raw_reference: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> RejectedInput:
        if not isinstance(received_at, datetime):
            received_at = UNKNOWN_RECEIVED_AT
        return RejectedInput(
            station_id=station_id,
            received_at_utc=received_at,
            stage="ingestion",
            reason_code=code,
            reason=reason,
            raw_reference=raw_reference,
            event_id=event_id,
        )


__all__ = ["IngestionAgent", "UNKNOWN_RECEIVED_AT"]
