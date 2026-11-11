"""Motor determinista de estados de detección: TABLA de reglas con ``rule_id`` estable.

Las reglas se evalúan en orden de prioridad; la primera cuya condición se cumple
propone un estado destino. Si el destino es el estado actual no hay decisión. Si la
transición no está en ``ALLOWED_TRANSITIONS`` se ignora (y el pipeline lo audita).
Cada cambio produce un ``DecisionRecord`` con ``rule_id``, ``reason`` legible,
``evidence_event_ids``, ``previous_state`` y ``requires_human_review``.

Criterio de INDEPENDENCIA técnica (configurable, ver ``PipelineConfig``):
- modo ``sensor_type`` (por defecto): dos observaciones son independientes solo si
  tienen DISTINTO ``sensor_type`` y el par no figura en ``non_independent_sensor_pairs``;
- modo ``sensor_type_or_station``: además, mismo tipo en DISTINTA estación, salvo
  ``remote_id``.
Dos recepciones de Remote ID (aunque sean de estaciones distintas) NUNCA son
independientes: son la misma autodeclaración del dron.

El motor no clasifica amenazas, no puntúa riesgo de personas y no recomienda acciones.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from src.contracts import DecisionRecord, DetectionState, Observation, SensorType
from src.tracking.agent_tracker import TrackedObservation, TrackState
from src.tracking.geo import combined_sigma, haversine_m

from .agent_evidence import EvidenceSummary
from .config import ENGINE_VERSION, PipelineConfig

S = DetectionState

ALLOWED_TRANSITIONS: dict[DetectionState, frozenset[DetectionState]] = {
    S.SIN_OBSERVACION: frozenset(
        {S.DETECCION_POSIBLE, S.DETECCION_CORROBORADA, S.REQUIERE_REVISION, S.DESCARTADA}
    ),
    S.DETECCION_POSIBLE: frozenset(
        {S.DETECCION_CORROBORADA, S.REQUIERE_REVISION, S.SEGUIMIENTO_PERDIDO}
    ),
    S.DETECCION_CORROBORADA: frozenset({S.REQUIERE_REVISION, S.SEGUIMIENTO_PERDIDO}),
    S.REQUIERE_REVISION: frozenset({S.SEGUIMIENTO_PERDIDO}),
    S.SEGUIMIENTO_PERDIDO: frozenset(
        {S.DETECCION_POSIBLE, S.REQUIERE_REVISION, S.DESCARTADA}
    ),
    S.DESCARTADA: frozenset(
        {S.DETECCION_POSIBLE, S.DETECCION_CORROBORADA, S.REQUIERE_REVISION}
    ),
}

HUMAN_REVIEW_RULE_ID = "R-HUM-01"
HUMAN_REVIEW_TARGETS = frozenset(
    {S.DETECCION_POSIBLE, S.DETECCION_CORROBORADA, S.REQUIERE_REVISION, S.DESCARTADA}
)


@dataclass(frozen=True)
class RuleContext:
    track: TrackState
    summary: EvidenceSummary
    current: DetectionState
    corroboration: Optional[tuple[Observation, Observation]]
    config: PipelineConfig


@dataclass(frozen=True)
class Rule:
    rule_id: str
    target: DetectionState
    description: str
    condition: Callable[[RuleContext], bool]
    reason: Callable[[RuleContext], str]
    evidence: Callable[[RuleContext], list[str]]


def _sim(ctx: RuleContext) -> str:
    return " [SIMULADO]" if ctx.track.is_simulated else ""


def _last_ids(ctx: RuleContext, n: int = 5) -> list[str]:
    obs = sorted(
        ctx.track.observations,
        key=lambda o: (o.observation.timestamp_utc, o.observation.event_id),
    )
    return [o.observation.event_id for o in obs[-n:]]


RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="R-PERD-01",
        target=S.SEGUIMIENTO_PERDIDO,
        description="Sin observaciones más allá de lost_timeout_s.",
        condition=lambda c: c.track.is_lost
        and c.current not in (S.SIN_OBSERVACION, S.DESCARTADA),
        reason=lambda c: (
            f"Sin observaciones desde {c.track.last_seen_utc.strftime('%H:%M:%S')} UTC, más de "
            f"{c.config.lost_timeout_s:.0f} s: el seguimiento se marca como perdido{_sim(c)}."
        ),
        evidence=lambda c: _last_ids(c, 3),
    ),
    Rule(
        rule_id="R-REV-01",
        target=S.REQUIERE_REVISION,
        description="Posiciones incompatibles para el mismo object_id dentro de la ventana.",
        condition=lambda c: not c.track.is_lost and bool(c.track.segment_contradictions()),
        reason=lambda c: (
            "Posiciones incompatibles para el mismo identificador de objeto "
            f"({c.track.object_id}) dentro de {c.config.correlation_window_s:.0f} s: "
            + "; ".join(
                f"{x.event_id} a {x.distance_m:.0f} m (umbral {x.threshold_m:.0f} m) de "
                f"{', '.join(x.reference_event_ids)}"
                for x in c.track.segment_contradictions()[:3]
            )
            + f". Se requiere revisión humana{_sim(c)}."
        ),
        evidence=lambda c: sorted(
            {x.event_id for x in c.track.segment_contradictions()}
            | {r for x in c.track.segment_contradictions() for r in x.reference_event_ids}
        ),
    ),
    Rule(
        rule_id="R-REAP-01",
        target=S.DETECCION_POSIBLE,
        description="Track perdido con nueva evidencia válida (reaparición).",
        condition=lambda c: c.current == S.SEGUIMIENTO_PERDIDO
        and not c.track.is_lost
        and bool(c.summary.valid_event_ids),
        reason=lambda c: (
            f"Reaparición tras pérdida: {len(c.summary.valid_event_ids)} observación(es) válida(s) "
            f"desde {c.track.segment_start_utc.strftime('%H:%M:%S')} UTC. La corroboración "
            f"debe volver a establecerse con evidencia nueva{_sim(c)}."
        ),
        evidence=lambda c: list(c.summary.valid_event_ids),
    ),
    Rule(
        rule_id="R-DESC-01",
        target=S.DESCARTADA,
        description="Toda la evidencia tiene classifier_score < min_classifier_score y no hay "
        "otra evidencia válida.",
        condition=lambda c: not c.track.is_lost
        and not c.summary.valid_event_ids
        and bool(c.summary.low_score_event_ids),
        reason=lambda c: (
            f"Toda la evidencia ({len(c.summary.low_score_event_ids)} obs.) tiene puntuación de "
            f"clasificador menor que {c.config.min_classifier_score:.2f} y no hay otra fuente: "
            f"se descarta por regla explícita{_sim(c)}."
        ),
        evidence=lambda c: list(c.summary.low_score_event_ids),
    ),
    Rule(
        rule_id="R-CORR-01",
        target=S.DETECCION_CORROBORADA,
        description="Dos fuentes técnicamente independientes y consistentes dentro de "
        "corroboration_window_s.",
        condition=lambda c: not c.track.is_lost and c.corroboration is not None,
        reason=lambda c: (
            "Evidencia de fuentes técnicamente independientes y consistentes: "
            f"{c.corroboration[0].sensor_type.value} ({c.corroboration[0].station_id}) y "
            f"{c.corroboration[1].sensor_type.value} ({c.corroboration[1].station_id}) con "
            f"{abs((c.corroboration[1].timestamp_utc - c.corroboration[0].timestamp_utc).total_seconds()):.1f}"
            f" s de diferencia. Se solicita revisión humana{_sim(c)}."
        )
        if c.corroboration
        else "",
        evidence=lambda c: sorted(o.event_id for o in c.corroboration) if c.corroboration else [],
    ),
    Rule(
        rule_id="R-POS-01",
        target=S.DETECCION_POSIBLE,
        description="Al menos una observación válida (una sola fuente o fuentes no independientes).",
        condition=lambda c: not c.track.is_lost and bool(c.summary.valid_event_ids),
        reason=lambda c: (
            f"{len(c.summary.valid_event_ids)} observación(es) válida(s) de "
            f"{', '.join(c.summary.sensor_types)} en {', '.join(c.summary.station_ids)}; "
            "sin fuentes técnicamente independientes que la corroboren"
            f"{_sim(c)}."
        ),
        evidence=lambda c: list(c.summary.valid_event_ids),
    ),
)


@dataclass(frozen=True)
class EngineOutcome:
    decision: Optional[DecisionRecord]
    rule_id: Optional[str]
    proposed: Optional[DetectionState]
    blocked: bool = False      # transición propuesta no permitida


class StateEngine:
    name = "state_engine"
    version = ENGINE_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config

    # ------------------------------------------------------------ independencia
    def are_independent(self, a: Observation, b: Observation) -> bool:
        cfg = self.config
        if a.sensor_type == b.sensor_type:
            if a.sensor_type == SensorType.REMOTE_ID:
                return False
            return cfg.independence_mode == "sensor_type_or_station" and a.station_id != b.station_id
        pair = {a.sensor_type.value, b.sensor_type.value}
        for x, y in cfg.non_independent_sensor_pairs:
            if {x, y} == pair:
                return False
        return True

    def are_consistent(self, a: Observation, b: Observation, sigma_a: float, sigma_b: float) -> bool:
        cfg = self.config
        dt = abs((a.timestamp_utc - b.timestamp_utc).total_seconds())
        if dt > cfg.corroboration_window_s:
            return False
        if a.has_position and b.has_position:
            d = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)  # type: ignore[arg-type]
            gate = min(
                cfg.max_association_distance_m,
                cfg.association_sigma_factor * combined_sigma(sigma_a, sigma_b)
                + cfg.max_speed_mps * dt,
            )
            return d <= gate
        # Si alguna no tiene posición, su consistencia proviene de la asociación
        # (object_id idéntico); no hay posición que comparar.
        return True

    def find_corroboration(
        self, track: TrackState, low_score: Callable[[Optional[float]], bool]
    ) -> Optional[tuple[Observation, Observation]]:
        cfg = self.config
        usable: list[TrackedObservation] = sorted(
            (
                to for to in track.segment_observations()
                if not to.conflicting
                and not low_score(to.observation.classifier_score)
                and to.quality >= cfg.min_corroboration_quality
            ),
            key=lambda to: (to.observation.timestamp_utc, to.observation.event_id),
        )

        def sig(o: Observation) -> float:
            u = o.measurement_uncertainty
            return float(u) if u else cfg.default_uncertainty_m

        for i, ta in enumerate(usable):
            a = ta.observation
            for tb in usable[i + 1:]:
                b = tb.observation
                if (b.timestamp_utc - a.timestamp_utc).total_seconds() > cfg.corroboration_window_s:
                    break
                if self.are_independent(a, b) and self.are_consistent(a, b, sig(a), sig(b)):
                    return a, b
        return None

    # --------------------------------------------------------------- evaluación
    def requires_review(self, state: DetectionState) -> bool:
        if state in (S.REQUIERE_REVISION, S.DETECCION_CORROBORADA, S.SEGUIMIENTO_PERDIDO):
            return True
        return state == S.DETECCION_POSIBLE and self.config.alert_on_posible

    def _decision_id(self, track_id: str, prev: DetectionState, new: DetectionState,
                     rule_id: str, now_utc: datetime, evidence: list[str]) -> str:
        raw = "|".join(
            [track_id, prev.value, new.value, rule_id, now_utc.isoformat(), ",".join(evidence)]
        )
        return "DEC-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def evaluate(
        self,
        track: TrackState,
        summary: EvidenceSummary,
        now_utc: datetime,
        low_score: Callable[[Optional[float]], bool],
    ) -> EngineOutcome:
        corroboration = self.find_corroboration(track, low_score)
        ctx = RuleContext(track, summary, track.state, corroboration, self.config)
        for rule in RULES:
            if not rule.condition(ctx):
                continue
            if rule.target == track.state:
                return EngineOutcome(None, rule.rule_id, rule.target)
            if rule.target not in ALLOWED_TRANSITIONS[track.state]:
                return EngineOutcome(None, rule.rule_id, rule.target, blocked=True)
            evidence = rule.evidence(ctx)
            decision = DecisionRecord(
                decision_id=self._decision_id(
                    track.track_id, track.state, rule.target, rule.rule_id, now_utc, evidence
                ),
                track_id=track.track_id,
                state=rule.target,
                previous_state=track.state,
                rule_id=rule.rule_id,
                reason=rule.reason(ctx),
                evidence_event_ids=evidence,
                requires_human_review=self.requires_review(rule.target),
                decided_at_utc=now_utc,
                engine_version=ENGINE_VERSION,
                is_simulated=track.is_simulated,
            )
            track.state = rule.target
            return EngineOutcome(decision, rule.rule_id, rule.target)
        return EngineOutcome(None, None, None)

    def human_review(
        self,
        track: TrackState,
        new_state: DetectionState,
        reviewer: str,
        note: Optional[str],
        now_utc: datetime,
    ) -> DecisionRecord:
        if new_state not in HUMAN_REVIEW_TARGETS:
            raise ValueError(f"estado no permitido para revisión humana: {new_state.value}")
        evidence = _last_ids(
            RuleContext(track, None, track.state, None, self.config), 5  # type: ignore[arg-type]
        )
        decision = DecisionRecord(
            decision_id=self._decision_id(
                track.track_id, track.state, new_state, HUMAN_REVIEW_RULE_ID, now_utc, evidence
            ),
            track_id=track.track_id,
            state=new_state,
            previous_state=track.state,
            rule_id=HUMAN_REVIEW_RULE_ID,
            reason=f"Revisión humana por {reviewer}: estado fijado a {new_state.value}"
            + (f". Nota: {note}" if note else ".")
            + (" [SIMULADO]" if track.is_simulated else ""),
            evidence_event_ids=evidence,
            requires_human_review=False,
            decided_at_utc=now_utc,
            engine_version=ENGINE_VERSION,
            is_simulated=track.is_simulated,
        )
        track.state = new_state
        # La evidencia anterior queda revisada: solo cuenta evidencia posterior.
        track.segment_start_utc = now_utc
        return decision


def rules_table() -> list[dict[str, str]]:
    """Tabla de reglas (para documentación y auditoría)."""
    rows = [
        {"rule_id": r.rule_id, "target": r.target.value, "description": r.description}
        for r in RULES
    ]
    rows.append(
        {
            "rule_id": HUMAN_REVIEW_RULE_ID,
            "target": "|".join(sorted(s.value for s in HUMAN_REVIEW_TARGETS)),
            "description": "Revisión humana explícita (OperationalPipeline.apply_human_review).",
        }
    )
    return rows
