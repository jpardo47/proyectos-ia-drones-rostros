"""Validación semántica de mensajes ``rid-demo-1`` ya parseados.

``validate_remote_id`` devuelve una lista de errores con la forma ``"CODIGO: motivo"``;
la lista vacía significa válido. ``check_remote_id`` devuelve además avisos
(``severity="warning"``) que no invalidan el mensaje.

Códigos de error estables:

- ``TIMESTAMP_NO_TZ``   el ``timestamp_utc`` del mensaje no tiene zona horaria.
- ``INVALID_RECEIVED_AT`` la hora de recepción inyectada no tiene zona horaria.
- ``FUTURE_TIMESTAMP``  el mensaje está fechado más de ``max_future_s`` después de su recepción.
- ``STALE``             el mensaje tiene más de ``max_age_s`` de antigüedad al recibirse.
- ``NON_FINITE_VALUE``  NaN o infinito en un campo numérico.
- ``OUT_OF_RANGE``      latitud, longitud, altitud, altura, precisión, velocidad o rumbo fuera de rango.
- ``POSITION_SENTINEL`` posición exactamente (0, 0): en OpenDroneID es el valor de "sin dato";
                        aquí se rechaza en lugar de interpretarse como una posición real.
- ``INCOHERENT_FIELDS`` ``height_agl_m`` sin ``height_reference``.
- ``INVALID_FIELD``     identificadores vacíos o demasiado largos.

Tolerancias por defecto (``RemoteIdLimits``), elegidas para drones pequeños en la demo:

==================  ==========  ===========================================================
parámetro           defecto     justificación
==================  ==========  ===========================================================
max_age_s           120 s       igual que ``ValidatorAgent``; más viejo no sirve para seguimiento
max_future_s        5 s         margen para desfase de reloj entre emisor y estación
min/max_altitude_m  -500/10000  geodésica o barométrica; Popayán está a ~1740 m s.n.m.
min/max_height_m    -100/3000   altura sobre terreno/despegue (puede ser negativa si baja del punto de despegue)
max_speed_mps       100 m/s     muy por encima de un multirrotor pequeño (~20-30 m/s)
max_accuracy_m      10000 m     una precisión peor no aporta posición útil
max_id_length       128         límite de ``Observation.object_id`` / ``event_id``
==================  ==========  ===========================================================

El rumbo (``track_deg``) se acepta en [0, 360]; 360 equivale a 0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Optional

from src.contracts import RemoteIdWireMessage


@dataclass(frozen=True)
class RemoteIdLimits:
    max_age_s: float = 120.0
    max_future_s: float = 5.0
    min_altitude_m: float = -500.0
    max_altitude_m: float = 10000.0
    min_height_m: float = -100.0
    max_height_m: float = 3000.0
    max_speed_mps: float = 100.0
    max_accuracy_m: float = 10000.0
    warn_accuracy_m: float = 1000.0   # precisión peor que esto genera un aviso
    max_id_length: int = 128


DEFAULT_LIMITS = RemoteIdLimits()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"

    def as_text(self) -> str:
        return f"{self.code}: {self.message}"


def _is_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() is not None


class _Checker:
    def __init__(self, limits: RemoteIdLimits) -> None:
        self.limits = limits
        self.issues: list[ValidationIssue] = []

    def error(self, code: str, field: str, message: str) -> None:
        self.issues.append(ValidationIssue(code, field, message, "error"))

    def warn(self, code: str, field: str, message: str) -> None:
        self.issues.append(ValidationIssue(code, field, message, "warning"))

    def number(self, field: str, value: Optional[float], lo: float, hi: float) -> bool:
        """True si el valor es utilizable (ausente o dentro de rango)."""
        if value is None:
            return True
        if not math.isfinite(value):
            self.error("NON_FINITE_VALUE", field, f"'{field}' no es un número finito")
            return False
        if value < lo or value > hi:
            self.error("OUT_OF_RANGE", field, f"'{field}'={value:g} fuera de [{lo:g}, {hi:g}]")
            return False
        return True

    def lat_lon(self, prefix: str, lat: float, lon: float) -> None:
        ok_lat = self.number(f"{prefix}.latitude", lat, -90.0, 90.0)
        ok_lon = self.number(f"{prefix}.longitude", lon, -180.0, 180.0)
        if ok_lat and ok_lon and lat == 0.0 and lon == 0.0:
            self.error(
                "POSITION_SENTINEL",
                prefix,
                f"'{prefix}' en (0, 0): valor centinela de 'sin posición', no es una ubicación válida",
            )

    def identifier(self, field: str, value: Optional[str], required: bool) -> None:
        if value is None:
            return
        if not value.strip():
            self.error("INVALID_FIELD", field, f"'{field}' está vacío")
        elif len(value) > self.limits.max_id_length:
            self.error(
                "INVALID_FIELD", field,
                f"'{field}' supera {self.limits.max_id_length} caracteres",
            )


def check_remote_id(
    msg: RemoteIdWireMessage,
    received_at_utc: datetime,
    limits: RemoteIdLimits = DEFAULT_LIMITS,
) -> list[ValidationIssue]:
    """Errores y avisos de un mensaje parseado. Determinista: no consulta el reloj."""
    c = _Checker(limits)
    lim = limits

    # --- identificadores -------------------------------------------------------
    c.identifier("message_id", msg.message_id, required=True)
    c.identifier("uas_id", msg.uas_id, required=False)
    if msg.uas_id is None:
        c.warn("UAS_ID_MISSING", "uas_id", "uas_id no reportado: el objeto queda sin identificador")

    # --- tiempo ----------------------------------------------------------------
    ts = msg.timestamp_utc
    ts_ok = _is_aware(ts)
    if not ts_ok:
        c.error("TIMESTAMP_NO_TZ", "timestamp_utc", "el timestamp del mensaje no incluye zona horaria")
    if not isinstance(received_at_utc, datetime) or not _is_aware(received_at_utc):
        c.error("INVALID_RECEIVED_AT", "received_at_utc", "la hora de recepción no incluye zona horaria")
    elif ts_ok:
        delta = (ts - received_at_utc).total_seconds()
        if delta > lim.max_future_s:
            c.error(
                "FUTURE_TIMESTAMP", "timestamp_utc",
                f"mensaje fechado {delta:.1f} s en el futuro (tolerancia {lim.max_future_s:g} s)",
            )
        elif -delta > lim.max_age_s:
            c.error(
                "STALE", "timestamp_utc",
                f"mensaje con {-delta:.1f} s de antigüedad (máximo {lim.max_age_s:g} s)",
            )

    # --- posición del dron -----------------------------------------------------
    d = msg.drone
    if d is not None:
        c.lat_lon("drone", d.latitude, d.longitude)
        c.number("drone.altitude_geodetic_m", d.altitude_geodetic_m, lim.min_altitude_m, lim.max_altitude_m)
        c.number("drone.altitude_pressure_m", d.altitude_pressure_m, lim.min_altitude_m, lim.max_altitude_m)
        c.number("drone.height_agl_m", d.height_agl_m, lim.min_height_m, lim.max_height_m)
        if d.height_agl_m is not None and d.height_reference is None:
            c.error(
                "INCOHERENT_FIELDS", "drone.height_reference",
                "'drone.height_agl_m' sin 'height_reference': no se sabe si es sobre terreno o sobre despegue",
            )
        if d.height_reference is not None and d.height_agl_m is None:
            c.warn(
                "HEIGHT_REFERENCE_WITHOUT_VALUE", "drone.height_reference",
                "'height_reference' presente sin 'height_agl_m'; se ignora",
            )
        for name, value in (
            ("drone.horizontal_accuracy_m", d.horizontal_accuracy_m),
            ("drone.vertical_accuracy_m", d.vertical_accuracy_m),
        ):
            if c.number(name, value, 0.0, lim.max_accuracy_m) and value is not None and value > lim.warn_accuracy_m:
                c.warn("LOW_ACCURACY", name, f"'{name}'={value:g} m: precisión muy baja")
        c.number("drone.speed_mps", d.speed_mps, 0.0, lim.max_speed_mps)
        c.number("drone.track_deg", d.track_deg, 0.0, 360.0)

    # --- estación de control y punto de despegue ------------------------------
    if msg.operator is not None:
        c.lat_lon("operator", msg.operator.latitude, msg.operator.longitude)
        c.number("operator.altitude_geodetic_m", msg.operator.altitude_geodetic_m, lim.min_altitude_m, lim.max_altitude_m)
    if msg.takeoff is not None:
        c.lat_lon("takeoff", msg.takeoff.latitude, msg.takeoff.longitude)
        c.number("takeoff.altitude_geodetic_m", msg.takeoff.altitude_geodetic_m, lim.min_altitude_m, lim.max_altitude_m)

    return c.issues


def validate_remote_id(
    msg: RemoteIdWireMessage,
    received_at_utc: datetime,
    limits: Optional[RemoteIdLimits] = None,
    **overrides: float,
) -> list[str]:
    """Errores ``"CODIGO: motivo"`` del mensaje; ``[]`` = válido.

    ``limits`` sustituye las tolerancias por defecto; ``overrides`` (p. ej.
    ``max_age_s=60``) ajusta campos sueltos de ``RemoteIdLimits``.
    """
    lim = limits or DEFAULT_LIMITS
    if overrides:
        lim = replace(lim, **overrides)
    return [i.as_text() for i in check_remote_id(msg, received_at_utc, lim) if i.severity == "error"]


def error_code(error_text: str) -> str:
    """Extrae el código de una cadena ``"CODIGO: motivo"``."""
    return error_text.split(":", 1)[0].strip()
