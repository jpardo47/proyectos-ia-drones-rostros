"""agent_quality: calidad y procedencia de cada observación ANTES de usarla como evidencia.

La ingesta (O2) ya validó formato y antigüedad; este agente vuelve a comprobar la
antigüedad contra el ``now_utc`` del lote (los lotes pueden procesarse más tarde) y
añade el estado de la estación:

- estación ``offline``  -> la observación NO aporta evidencia nueva (STATION_OFFLINE);
- estación ``degraded`` -> la calidad se multiplica por ``degraded_quality_factor``;
- antigüedad > ``max_observation_age_s``             -> STALE;
- timestamp > now + ``max_future_s``                   -> FUTURE_TIMESTAMP;
- calidad efectiva < ``min_quality``                   -> LOW_QUALITY.

Calidad efectiva = (``sensor_quality`` o ``default_sensor_quality``) x factor de estación.
La procedencia (``data_origin``, ``is_simulated``) se registra siempre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional

from src.contracts import Observation, StationStatus

from .config import PipelineConfig

QUALITY_VERSION = "1.0.0"


@dataclass(frozen=True)
class QualityAssessment:
    accepted: bool
    score: float
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    factors: dict[str, Any] = field(default_factory=dict)


class QualityAgent:
    name = "agent_quality"
    version = QUALITY_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config

    def assess(
        self,
        obs: Observation,
        now_utc: datetime,
        station_status: Mapping[str, StationStatus],
    ) -> QualityAssessment:
        cfg = self.config
        status = station_status.get(obs.station_id, StationStatus.ONLINE)
        base = obs.sensor_quality if obs.sensor_quality is not None else cfg.default_sensor_quality
        factor = cfg.degraded_quality_factor if status == StationStatus.DEGRADED else 1.0
        score = round(base * factor, 6)
        age_s = (now_utc - obs.timestamp_utc).total_seconds()
        factors = {
            "station_status": status.value,
            "sensor_quality": obs.sensor_quality,
            "base_quality": base,
            "station_factor": factor,
            "age_s": round(age_s, 3),
            "data_origin": obs.data_origin.value,
            "is_simulated": obs.is_simulated,
        }
        if status == StationStatus.OFFLINE:
            return QualityAssessment(
                False, 0.0, "STATION_OFFLINE",
                f"La estación {obs.station_id} figura fuera de línea: la observación no se "
                "usa como evidencia nueva.",
                factors,
            )
        if age_s > cfg.max_observation_age_s:
            return QualityAssessment(
                False, score, "STALE",
                f"Observación con {age_s:.1f} s de antigüedad (máximo "
                f"{cfg.max_observation_age_s:.0f} s).",
                factors,
            )
        if -age_s > cfg.max_future_s:
            return QualityAssessment(
                False, score, "FUTURE_TIMESTAMP",
                f"Timestamp {-age_s:.1f} s en el futuro respecto al lote (tolerancia "
                f"{cfg.max_future_s:.0f} s).",
                factors,
            )
        if score < cfg.min_quality:
            return QualityAssessment(
                False, score, "LOW_QUALITY",
                f"Calidad efectiva {score:.2f} por debajo del mínimo {cfg.min_quality:.2f}"
                + (" (estación degradada)." if factor < 1.0 else "."),
                factors,
            )
        return QualityAssessment(True, score, factors=factors)
