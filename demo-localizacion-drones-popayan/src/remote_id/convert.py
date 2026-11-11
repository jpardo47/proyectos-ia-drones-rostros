"""Conversión de un mensaje ``rid-demo-1`` VALIDADO a ``IngestionResult``.

Reglas:

- La ``Observation`` lleva SOLO la posición reportada del **dron**. La estación de
  control (``operator``) y el punto de despegue (``takeoff``) van en
  ``related_locations`` con ``LocationRole.CONTROL_STATION`` / ``TAKEOFF_POINT``.
  Si faltan no se rellenan ni se deducen: se añade un aviso.
- ``object_id = uas_id``. ``operator_id`` NUNCA se copia ni se usa: es un dato
  administrativo y no sirve para identificar a ninguna persona.
- Origen: ``msg.is_simulated=True`` -> ``data_origin=simulation``. Si no es simulado,
  se usa el origen que indique quien llama (``replay`` por defecto, ``sensor`` o
  ``manual``); pedir ``simulation`` para un mensaje no simulado es un error.
- Altitud (orden de preferencia documentado):
    1. ``altitude_geodetic_m``  -> referencia ``wgs84`` (GNSS, absoluta)
    2. ``altitude_pressure_m``  -> referencia ``msl``   (barométrica)
    3. ``height_agl_m``         -> referencia ``agl`` o ``takeoff`` según ``height_reference``
  Si no hay ninguna, la observación va sin altitud.
- ``measurement_uncertainty = horizontal_accuracy_m``. En OpenDroneID la precisión es
  una cota de ~95 %; usarla como 1-sigma sobreestima la incertidumbre (conservador).
- ``event_id`` determinista: ``rid-`` + SHA-256(station_id | message_id)[:32].
- ``raw_reference``: ``rid-demo-1:<station_id>:<message_id>``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from src.contracts import (
    RID_WIRE_VERSION,
    AltitudeReference,
    DataOrigin,
    IngestionResult,
    LocationRole,
    Observation,
    RemoteIdWireMessage,
    ReportedLocation,
    SensorType,
)

from .validation import DEFAULT_LIMITS, RemoteIdLimits, check_remote_id

#: Aviso si el mensaje llegó con más retraso que esto (s), aunque siga siendo válido.
LATENCY_WARNING_S = 10.0

WARN_NO_CONTROL_STATION = "estación de control no reportada"
WARN_NO_TAKEOFF = "punto de despegue no reportado"
WARN_TAKEOFF_WITHOUT_CONTROL = "punto de despegue reportado sin estación de control"
WARN_NO_DRONE_POSITION = "posición del dron no reportada: observación sin coordenadas"
WARN_NO_ALTITUDE = "altitud del dron no reportada"
WARN_NO_ACCURACY = "precisión horizontal no reportada: incertidumbre desconocida"
WARN_UNVERIFIED = "ubicaciones auto-reportadas por Remote ID; no verificadas"


def make_event_id(station_id: str, message_id: str) -> str:
    digest = hashlib.sha256(f"{station_id}|{message_id}".encode("utf-8")).hexdigest()
    return f"rid-{digest[:32]}"


def make_raw_reference(station_id: str, message_id: str) -> str:
    return f"{RID_WIRE_VERSION}:{station_id}:{message_id}"[:512]


def select_altitude(msg: RemoteIdWireMessage) -> tuple[Optional[float], Optional[AltitudeReference]]:
    d = msg.drone
    if d is None:
        return None, None
    if d.altitude_geodetic_m is not None:
        return d.altitude_geodetic_m, AltitudeReference.WGS84
    if d.altitude_pressure_m is not None:
        return d.altitude_pressure_m, AltitudeReference.MSL
    if d.height_agl_m is not None and d.height_reference is not None:
        ref = AltitudeReference.AGL if d.height_reference == "agl" else AltitudeReference.TAKEOFF
        return d.height_agl_m, ref
    return None, None


def to_ingestion_result(
    msg: RemoteIdWireMessage,
    station_id: str,
    received_at_utc: datetime,
    *,
    data_origin: DataOrigin = DataOrigin.REPLAY,
    limits: RemoteIdLimits = DEFAULT_LIMITS,
) -> IngestionResult:
    """Normaliza un mensaje válido. Lanza ``ValueError`` si el mensaje no pasa la validación
    o si el origen pedido es incoherente (el ``IngestionAgent`` captura ambos casos)."""
    issues = check_remote_id(msg, received_at_utc, limits)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise ValueError("mensaje Remote ID no válido: " + "; ".join(e.as_text() for e in errors))

    if msg.is_simulated:
        origin = DataOrigin.SIMULATION
    else:
        if data_origin == DataOrigin.SIMULATION:
            raise ValueError("origen 'simulation' pedido para un mensaje con is_simulated=false")
        origin = data_origin

    warnings: list[str] = [i.message for i in issues if i.severity == "warning"]

    d = msg.drone
    lat = lon = uncertainty = None
    if d is None:
        warnings.append(WARN_NO_DRONE_POSITION)
    else:
        lat, lon = d.latitude, d.longitude
        uncertainty = d.horizontal_accuracy_m
        if uncertainty is None:
            warnings.append(WARN_NO_ACCURACY)
    altitude, altitude_ref = select_altitude(msg)
    if d is not None and altitude is None:
        warnings.append(WARN_NO_ALTITUDE)

    related: list[ReportedLocation] = []
    if msg.operator is not None:
        op = msg.operator
        related.append(
            ReportedLocation(
                role=LocationRole.CONTROL_STATION,
                latitude=op.latitude,
                longitude=op.longitude,
                altitude=op.altitude_geodetic_m,
                altitude_reference=AltitudeReference.WGS84 if op.altitude_geodetic_m is not None else None,
                detail=op.location_kind.value,
            )
        )
    else:
        warnings.append(WARN_NO_CONTROL_STATION)
    if msg.takeoff is not None:
        tk = msg.takeoff
        related.append(
            ReportedLocation(
                role=LocationRole.TAKEOFF_POINT,
                latitude=tk.latitude,
                longitude=tk.longitude,
                altitude=tk.altitude_geodetic_m,
                altitude_reference=AltitudeReference.WGS84 if tk.altitude_geodetic_m is not None else None,
                detail="reported",
            )
        )
        if msg.operator is None:
            warnings.append(WARN_TAKEOFF_WITHOUT_CONTROL)
    else:
        warnings.append(WARN_NO_TAKEOFF)
    if lat is not None or related:
        warnings.append(WARN_UNVERIFIED)

    latency = (received_at_utc - msg.timestamp_utc).total_seconds()
    if latency > LATENCY_WARNING_S:
        warnings.append(f"mensaje recibido con {latency:.1f} s de retraso")

    observation = Observation(
        event_id=make_event_id(station_id, msg.message_id),
        station_id=station_id,
        sensor_type=SensorType.REMOTE_ID,
        timestamp_utc=msg.timestamp_utc,
        data_origin=origin,
        is_simulated=msg.is_simulated,
        object_id=msg.uas_id,
        latitude=lat,
        longitude=lon,
        altitude=altitude,
        altitude_reference=altitude_ref,
        measurement_uncertainty=uncertainty,
        raw_reference=make_raw_reference(station_id, msg.message_id),
    )
    return IngestionResult(observation=observation, related_locations=related, warnings=warnings)
