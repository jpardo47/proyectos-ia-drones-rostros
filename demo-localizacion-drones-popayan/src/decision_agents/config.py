"""Parámetros del motor de fusión y decisiones (O3).

Vive en un módulo propio para que ``src.correlation``, ``src.tracking`` y
``src.decision_agents`` lo compartan sin importaciones circulares. Se reexporta
desde ``src.decision_agents.pipeline`` (firma de INTERFACES.md).

Todos los valores por defecto están documentados en ``docs/motor-decisiones.md``.
Son parámetros de software para la SIMULACIÓN; no describen el alcance ni la
precisión de ningún equipo real.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ENGINE_VERSION = "o3-motor-decisiones-1.0.0"


class PipelineConfig(BaseModel):
    """Umbrales del pipeline operativo. Inmutable una vez creado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- Correlación / asociación -------------------------------------------
    correlation_window_s: float = Field(
        default=10.0, gt=0,
        description="Ventana temporal (s) en la que una observación puede asociarse a un track "
        "o compararse con sus puntos.",
    )
    max_association_distance_m: float = Field(
        default=300.0, gt=0,
        description="Tope absoluto (m) de la puerta de asociación espacial para observaciones "
        "sin object_id.",
    )
    association_sigma_factor: float = Field(
        default=3.0, gt=0,
        description="Multiplicador de la incertidumbre combinada sqrt(s1^2+s2^2) en las puertas.",
    )
    default_uncertainty_m: float = Field(
        default=30.0, gt=0,
        description="Incertidumbre horizontal (1-sigma, m) supuesta si la observación no la trae.",
    )
    max_speed_mps: float = Field(
        default=30.0, ge=0,
        description="Velocidad máxima supuesta (m/s) para ensanchar la puerta con |dt|.",
    )
    association_max_gap_s: float = Field(
        default=30.0, gt=0,
        description="Hueco temporal máximo (s) entre una observación anónima con posición y el "
        "punto más cercano en el tiempo de un track activo para considerarlo candidato. La "
        "puerta crece con v_max*|dt| (acotada por max_association_distance_m), de modo que "
        "detecciones fallidas intermitentes no fragmentan el track.",
    )
    ambiguity_ratio: float = Field(
        default=0.5, gt=0, lt=1,
        description="Con varios candidatos, se asocia al mejor solo si su distancia normalizada "
        "(d/puerta) es < ambiguity_ratio x la del segundo. Si no, la observación queda SIN "
        "asociar (no se crea track nuevo ni se elige arbitrariamente).",
    )
    contradiction_distance_m: float = Field(
        default=500.0, gt=0,
        description="Distancia mínima (m) para declarar posiciones incompatibles del MISMO objeto.",
    )

    # --- Seguimiento ---------------------------------------------------------
    lost_timeout_s: float = Field(
        default=30.0, gt=0,
        description="Sin observaciones más allá de este tiempo (s) -> SEGUIMIENTO_PERDIDO.",
    )

    # --- Corroboración -------------------------------------------------------
    corroboration_window_s: float = Field(
        default=5.0, gt=0,
        description="Diferencia temporal máxima (s) entre dos observaciones independientes para "
        "que cuenten como corroboración.",
    )
    independence_mode: Literal["sensor_type", "sensor_type_or_station"] = Field(
        default="sensor_type",
        description="'sensor_type': solo distinto tipo de sensor es independiente. "
        "'sensor_type_or_station': además, mismo tipo (no remote_id) en distinta estación.",
    )
    non_independent_sensor_pairs: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pares de tipos de sensor que NO se consideran independientes entre sí "
        "(p. ej. [('remote_id','rf')] si el detector RF solo recibe la propia baliza).",
    )
    min_corroboration_quality: float = Field(
        default=0.5, ge=0, le=1,
        description="Calidad mínima de cada observación para contar en una corroboración.",
    )

    # --- Calidad -------------------------------------------------------------
    max_observation_age_s: float = Field(
        default=120.0, gt=0,
        description="Observaciones más antiguas que esto respecto a now_utc se rechazan (STALE).",
    )
    max_future_s: float = Field(
        default=5.0, ge=0,
        description="Tolerancia (s) a timestamps en el futuro respecto a now_utc.",
    )
    min_quality: float = Field(
        default=0.2, ge=0, le=1,
        description="Calidad efectiva mínima para aceptar una observación como evidencia.",
    )
    default_sensor_quality: float = Field(
        default=0.7, ge=0, le=1,
        description="Calidad supuesta si sensor_quality es None (conservadora, < 1).",
    )
    degraded_quality_factor: float = Field(
        default=0.5, ge=0, le=1,
        description="Factor que multiplica la calidad si la estación está 'degraded'.",
    )

    # --- Clasificador / descarte --------------------------------------------
    min_classifier_score: float = Field(
        default=0.3, ge=0, le=1,
        description="Una observación con classifier_score menor no cuenta como evidencia válida; "
        "un track cuya evidencia es solo de este tipo pasa a DESCARTADA (R-DESC-01).",
    )

    # --- Alertas -------------------------------------------------------------
    alert_on_posible: bool = Field(
        default=False,
        description="Si True, también se genera alerta informativa para DETECCION_POSIBLE.",
    )
    alert_lost_only_if_alerted: bool = Field(
        default=True,
        description="SEGUIMIENTO_PERDIDO solo genera alerta si el track ya había generado alguna "
        "alerta antes (evita una alerta por cada detección aislada que caduca).",
    )
    alert_cooldown_s: float = Field(
        default=300.0, ge=0,
        description="No se repite la alerta del MISMO estado para el MISMO track antes de este "
        "tiempo (s); la decisión sí se registra y la supresión se audita.",
    )

    # --- Deduplicación -------------------------------------------------------
    dedup_retention_s: float = Field(
        default=3600.0, gt=0,
        description="Tiempo (s) que se recuerdan event_id y claves de contenido para deduplicar.",
    )
    position_round_decimals: int = Field(
        default=7, ge=0, le=10,
        description="Decimales de lat/lon usados en la clave de contenido equivalente.",
    )

    def fingerprint(self) -> str:
        """Hash estable de la configuración (se registra en auditoría)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
