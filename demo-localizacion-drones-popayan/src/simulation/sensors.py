"""Modelo de deteccion de sensores VIRTUALES (parametros HIPOTETICOS).

Ningun parametro de este modulo representa un hardware real ni demuestra alcance
fisico alguno: sirven para ejercitar el software (ingesta, correlacion, estados).

- Estaciones ``CIV-*`` (con coordenadas ficticias): la probabilidad de deteccion
  decae con la distancia, ``p = p_max * exp(-(d / range_m) ** shape)``.
- Nodos ``INST-SIM-*`` (SIN coordenadas): fuentes logicas con probabilidad de
  recepcion configurable e INDEPENDIENTE de la distancia.
- Acustico: solo clasificacion (sin coordenadas). RF: solo deteccion (sin posicion).
  Optico y radar: posicion con incertidumbre.
"""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from src.contracts import (
    AltitudeReference,
    DataOrigin,
    Observation,
    RemoteIdWireMessage,
    RidDronePosition,
    RidIdType,
    RidOperatorLocation,
    RidOperatorLocationKind,
    RidTakeoffPoint,
    SensorType,
)

GROUND_ELEVATION_M = 1738.0  # elevacion de terreno hipotetica y constante (WGS84/MSL)
RID_GNSS_SIGMA_M = 3.0       # error GNSS de la posicion que el propio dron reporta


@dataclass(frozen=True)
class SensorModel:
    sensor: str
    p_max: float          # probabilidad maxima de deteccion
    range_m: float        # distancia caracteristica HIPOTETICA
    shape: float          # pendiente de la caida
    interval_s: float     # cadencia de reporte
    latency_min_s: float
    latency_max_s: float
    pos_sigma_base_m: float = 0.0
    pos_sigma_per_m: float = 0.0   # crecimiento de la incertidumbre con la distancia


SENSOR_MODELS: dict[str, SensorModel] = {
    "remote_id": SensorModel("remote_id", 0.95, 4000.0, 3.0, 2.0, 0.05, 0.60),
    "acoustic": SensorModel("acoustic", 0.90, 1200.0, 2.0, 2.0, 0.10, 0.80),
    "rf": SensorModel("rf", 0.90, 2500.0, 2.5, 3.0, 0.05, 0.50),
    "optical": SensorModel("optical", 0.85, 1500.0, 3.0, 3.0, 0.10, 0.90, 10.0, 0.01),
    "radar": SensorModel("radar", 0.90, 6000.0, 3.0, 2.0, 0.05, 0.40, 15.0, 0.004),
}

INST_FIXED_POS_SIGMA_M = 30.0  # nodo logico sin posicion: incertidumbre fija del radar abstracto


def detection_probability(model: SensorModel, distance_m: float, range_scale: float = 1.0) -> float:
    rng_m = model.range_m * max(range_scale, 1e-6)
    return model.p_max * math.exp(-((max(distance_m, 0.0) / rng_m) ** model.shape))


def position_sigma(model: SensorModel, distance_m: Optional[float]) -> float:
    if distance_m is None:
        return INST_FIXED_POS_SIGMA_M
    return model.pos_sigma_base_m + model.pos_sigma_per_m * distance_m


def latency(model: SensorModel, rng: random.Random) -> float:
    return rng.uniform(model.latency_min_s, model.latency_max_s)


# --------------------------------------------------------------------------- #
# Constructores de payloads validos
# --------------------------------------------------------------------------- #


def build_remote_id_payload(
    *, message_id: str, ts: datetime, uas_id: str, lat: float, lon: float, agl_m: float,
    speed_mps: float, track_deg: float, rng: random.Random,
    operator: Optional[tuple[float, float]] = None,
    takeoff: Optional[tuple[float, float]] = None,
    operator_id: Optional[str] = None,
) -> dict[str, Any]:
    """Mensaje ``rid-demo-1`` valido. ``operator``/``takeoff`` son (lat, lon) o None (DESCONOCIDO)."""
    msg = RemoteIdWireMessage(
        message_id=message_id,
        timestamp_utc=ts,
        is_simulated=True,
        uas_id=uas_id,
        id_type=RidIdType.SERIAL_NUMBER,
        ua_type="multirotor",
        drone=RidDronePosition(
            latitude=lat,
            longitude=lon,
            altitude_geodetic_m=GROUND_ELEVATION_M + agl_m + rng.gauss(0, 2.0),
            altitude_pressure_m=GROUND_ELEVATION_M + agl_m + rng.gauss(0, 4.0),
            height_agl_m=agl_m,
            height_reference="agl",
            horizontal_accuracy_m=RID_GNSS_SIGMA_M,
            vertical_accuracy_m=4.0,
            speed_mps=speed_mps,
            track_deg=track_deg,
        ),
        operator=(
            RidOperatorLocation(latitude=operator[0], longitude=operator[1],
                                altitude_geodetic_m=GROUND_ELEVATION_M,
                                location_kind=RidOperatorLocationKind.FIXED)
            if operator else None
        ),
        takeoff=(
            RidTakeoffPoint(latitude=takeoff[0], longitude=takeoff[1], altitude_geodetic_m=GROUND_ELEVATION_M)
            if takeoff else None
        ),
        operator_id=operator_id if operator else None,
    )
    return msg.model_dump(mode="json")


def build_observation_payload(
    *, event_id: str, station_id: str, sensor: str, ts: datetime,
    object_id: Optional[str] = None, classifier_score: Optional[float] = None,
    lat: Optional[float] = None, lon: Optional[float] = None, agl_m: Optional[float] = None,
    uncertainty_m: Optional[float] = None, quality: Optional[float] = None,
    raw_reference: Optional[str] = None,
) -> dict[str, Any]:
    obs = Observation(
        event_id=event_id,
        station_id=station_id,
        sensor_type=SensorType(sensor),
        timestamp_utc=ts,
        data_origin=DataOrigin.SIMULATION,
        is_simulated=True,
        object_id=object_id,
        classification="drone",
        classifier_score=classifier_score,
        latitude=lat,
        longitude=lon,
        altitude=agl_m if lat is not None else None,
        altitude_reference=AltitudeReference.AGL if lat is not None else None,
        measurement_uncertainty=uncertainty_m,
        sensor_quality=quality,
        raw_reference=raw_reference,
    )
    return obs.model_dump(mode="json")


def acoustic_score(distance_m: float, rng: random.Random) -> float:
    base = 0.97 * math.exp(-distance_m / 1500.0) + rng.gauss(0, 0.04)
    return round(min(0.99, max(0.35, base)), 3)


def rf_score(distance_m: float, rng: random.Random) -> float:
    base = 0.95 * math.exp(-distance_m / 4000.0) + rng.gauss(0, 0.05)
    return round(min(0.99, max(0.30, base)), 3)


# --------------------------------------------------------------------------- #
# Payloads MALFORMADOS a proposito (escenario ``malformados``)
# --------------------------------------------------------------------------- #

MALFORMED_KINDS = [
    "rid_sin_message_id",
    "rid_latitud_999",
    "rid_timestamp_sin_zona",
    "rid_timestamp_futuro",
    "rid_tipos_erroneos",
    "rid_version_desconocida",
    "rid_vacio",
    "obs_sin_event_id",
    "obs_latitud_999",
    "obs_timestamp_sin_zona",
    "obs_timestamp_futuro",
    "obs_acustico_con_coordenadas",
    "obs_tipos_erroneos",
    "obs_simulacion_incoherente",
]


def make_malformed_payload(kind: str, template_rid: dict[str, Any], template_obs: dict[str, Any],
                           ts: datetime) -> tuple[str, dict[str, Any]]:
    """Devuelve ``(raw_kind, payload)`` roto de una forma concreta y conocida."""
    rid = copy.deepcopy(template_rid)
    obs = copy.deepcopy(template_obs)
    naive = ts.replace(tzinfo=None).isoformat()
    future = (ts + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    if kind == "rid_sin_message_id":
        rid.pop("message_id", None)
        return "remote_id", rid
    if kind == "rid_latitud_999":
        rid["drone"]["latitude"] = 999.0
        return "remote_id", rid
    if kind == "rid_timestamp_sin_zona":
        rid["timestamp_utc"] = naive
        return "remote_id", rid
    if kind == "rid_timestamp_futuro":
        rid["timestamp_utc"] = future
        return "remote_id", rid
    if kind == "rid_tipos_erroneos":
        rid["drone"]["latitude"] = "norte"
        rid["drone"]["speed_mps"] = "rapido"
        return "remote_id", rid
    if kind == "rid_version_desconocida":
        rid["schema_version"] = "rid-demo-9"
        return "remote_id", rid
    if kind == "rid_vacio":
        return "remote_id", {}
    if kind == "obs_sin_event_id":
        obs.pop("event_id", None)
        return "observation", obs
    if kind == "obs_latitud_999":
        obs.update(sensor_type="optical", latitude=999.0, longitude=-76.6, altitude=50.0, altitude_reference="agl")
        return "observation", obs
    if kind == "obs_timestamp_sin_zona":
        obs["timestamp_utc"] = naive
        return "observation", obs
    if kind == "obs_timestamp_futuro":
        obs["timestamp_utc"] = future
        return "observation", obs
    if kind == "obs_acustico_con_coordenadas":
        obs.update(sensor_type="acoustic", latitude=2.44, longitude=-76.6)
        return "observation", obs
    if kind == "obs_tipos_erroneos":
        obs["classifier_score"] = "alto"
        obs["sensor_type"] = 42
        return "observation", obs
    if kind == "obs_simulacion_incoherente":
        obs["is_simulated"] = False
        return "observation", obs
    raise ValueError(f"tipo de payload malformado desconocido: {kind}")
