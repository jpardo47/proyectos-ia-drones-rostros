"""Pipeline operativo determinista de O3 (firma en ``src/contracts/INTERFACES.md``).

``OperationalPipeline.process_batch`` recibe observaciones YA validadas en formato y
antigüedad por O2 y ejecuta, en orden:

1. ordenar el lote (con object_id primero; luego timestamp, estación, tipo de sensor,
   event_id) -> independencia del orden de llegada;
2. ``agent_correlator``: duplicados por ``event_id`` y por contenido equivalente;
3. ``agent_quality``: estado de estación, antigüedad, futuro, calidad mínima;
4. ``agent_correlator``: asociación conservadora a un track (o track nuevo);
5. ``agent_tracker``: incorporación (puntos con incertidumbre, contradicciones);
6. ``agent_tracker``: pérdidas por caducidad respecto a ``now_utc``;
7. ``agent_evidence`` + ``state_engine``: decisión por track (tabla de reglas);
8. ``agent_alerts``: alertas informativas;
9. ``agent_audit``: un ``AuditEvent`` por paso relevante.

Sin reloj de pared (``now_utc`` siempre inyectado), sin aleatoriedad, IDs deterministas.
Mantiene estado entre lotes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional, Sequence

from src.audit.agent_audit import AuditAgent
from src.contracts import (
    Alert,
    DecisionRecord,
    DetectionState,
    Observation,
    PipelineResult,
    RejectedInput,
    StationStatus,
    Track,
)
from src.correlation.agent_correlator import CorrelatorAgent
from src.tracking.agent_tracker import TrackerAgent

from .agent_alerts import AlertsAgent
from .agent_evidence import EvidenceAgent
from .agent_quality import QualityAgent
from .config import ENGINE_VERSION, PipelineConfig
from .state_engine import StateEngine

__all__ = ["ENGINE_VERSION", "PipelineConfig", "OperationalPipeline"]

PIPELINE_ACTOR = "pipeline_o3"


def _sort_key(o: Observation) -> tuple:
    # Primero las observaciones con object_id (anclan los tracks identificados) y luego
    # las anónimas; dentro de cada grupo, orden temporal. Así una detección anónima del
    # mismo instante puede asociarse al track identificado en lugar de crear uno aparte.
    return (o.object_id is None, o.timestamp_utc, o.station_id, o.sensor_type.value, o.event_id)


class OperationalPipeline:
    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig()
        self.correlator = CorrelatorAgent(self.config)
        self.tracker = TrackerAgent(self.config)
        self.quality = QualityAgent(self.config)
        self.evidence = EvidenceAgent(self.config)
        self.engine = StateEngine(self.config)
        self.alerts = AlertsAgent(self.config)
        self.audit = AuditAgent(ENGINE_VERSION)
        self._station_status: dict[str, StationStatus] = {}
        self._last_now: Optional[datetime] = None

    # ----------------------------------------------------------------- consulta
    def current_tracks(self) -> list[Track]:
        return self.tracker.snapshot()

    def current_states(self) -> dict[str, DetectionState]:
        return {tid: self.tracker.tracks[tid].state for tid in sorted(self.tracker.tracks)}

    # -------------------------------------------------------------------- lote
    def process_batch(
        self,
        observations: Sequence[Observation],
        now_utc: datetime,
        station_status: Mapping[str, StationStatus] | None = None,
    ) -> PipelineResult:
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            raise ValueError("now_utc debe incluir zona horaria (UTC)")
        cfg = self.config
        if station_status:
            for sid in sorted(station_status):
                self._station_status[sid] = StationStatus(station_status[sid])
        self._last_now = now_utc

        self.audit.record(
            now_utc, PIPELINE_ACTOR, "lote_recibido", "lote",
            {
                "observaciones": len(observations),
                "engine_version": ENGINE_VERSION,
                "config_fingerprint": cfg.fingerprint(),
                "station_status": {k: v.value for k, v in sorted(self._station_status.items())},
                "agentes": {
                    a.name: a.version
                    for a in (self.correlator, self.tracker, self.quality, self.evidence,
                              self.engine, self.alerts, self.audit)
                },
            },
        )

        accepted: list[Observation] = []
        rejected: list[RejectedInput] = []
        duplicates: list[str] = []
        touched: set[str] = set()

        for obs in sorted(observations, key=_sort_key):
            dup = self.correlator.check_duplicate(obs)
            if dup.is_duplicate:
                duplicates.append(obs.event_id)
                self.audit.record(
                    now_utc, self.correlator.name, "duplicado_descartado", obs.event_id,
                    {"reason_code": dup.reason_code, "original_event_id": dup.original_event_id},
                )
                continue

            qa = self.quality.assess(obs, now_utc, self._station_status)
            if not qa.accepted:
                rejected.append(
                    RejectedInput(
                        station_id=obs.station_id,
                        received_at_utc=now_utc,
                        stage="validation",
                        reason_code=qa.reason_code or "REJECTED",
                        reason=qa.reason or "Observación no utilizable como evidencia.",
                        raw_reference=obs.raw_reference,
                        event_id=obs.event_id,
                    )
                )
                self.audit.record(
                    now_utc, self.quality.name, "observacion_rechazada", obs.event_id,
                    {"reason_code": qa.reason_code, "reason": qa.reason, **qa.factors},
                )
                continue

            self.correlator.register(obs)
            accepted.append(obs)
            self.audit.record(
                now_utc, self.quality.name, "observacion_aceptada", obs.event_id,
                {"quality": qa.score, "sensor_type": obs.sensor_type.value,
                 "station_id": obs.station_id, **qa.factors},
            )

            assoc = self.correlator.associate(
                obs, self.tracker.tracks, self.tracker.by_object, self.tracker.sigma_of(obs),
                self.tracker.by_presence,
            )
            if assoc.track_id is None and not assoc.create_track:
                self.audit.record(
                    now_utc, self.correlator.name, "observacion_no_asociada", obs.event_id,
                    {"motivo": assoc.reason, "candidatos": list(assoc.candidate_track_ids)},
                )
                continue
            if assoc.track_id is None:
                track = self.tracker.create_track(obs, presence=assoc.presence)
                self.audit.record(
                    now_utc, self.tracker.name, "track_creado", track.track_id,
                    {"event_id": obs.event_id, "object_id": obs.object_id,
                     "is_simulated": obs.is_simulated, "motivo": assoc.reason,
                     "ambigua": assoc.ambiguous, "candidatos": list(assoc.candidate_track_ids)},
                )
            else:
                track = self.tracker.tracks[assoc.track_id]
                self.audit.record(
                    now_utc, self.correlator.name, "observacion_asociada", track.track_id,
                    {"event_id": obs.event_id, "metodo": assoc.method, "motivo": assoc.reason,
                     "candidatos": list(assoc.candidate_track_ids)},
                )
            outcome = self.tracker.add_observation(track, obs, qa.score, now_utc)
            touched.add(track.track_id)
            if outcome.reopened:
                self.audit.record(
                    now_utc, self.tracker.name, "track_reabierto", track.track_id,
                    {"event_id": obs.event_id},
                )
            if outcome.contradiction is not None:
                c = outcome.contradiction
                self.audit.record(
                    now_utc, self.tracker.name, "contradiccion_detectada", track.track_id,
                    {"event_id": c.event_id, "referencia": list(c.reference_event_ids),
                     "distancia_m": c.distance_m, "umbral_m": c.threshold_m},
                )

        pruned = self.correlator.prune(now_utc)

        for tid in self.tracker.update_lost(now_utc):
            touched.add(tid)
            self.audit.record(
                now_utc, self.tracker.name, "seguimiento_caducado", tid,
                {"last_seen_utc": self.tracker.tracks[tid].last_seen_utc,
                 "lost_timeout_s": cfg.lost_timeout_s},
            )

        decisions: list[DecisionRecord] = []
        alerts: list[Alert] = []
        for tid in sorted(self.tracker.tracks):
            track = self.tracker.tracks[tid]
            summary = self.evidence.summarize(track)
            outcome = self.engine.evaluate(track, summary, now_utc, self.evidence.is_low_score)
            if outcome.blocked:
                self.audit.record(
                    now_utc, self.engine.name, "transicion_no_permitida", tid,
                    {"rule_id": outcome.rule_id, "estado": track.state.value,
                     "propuesto": outcome.proposed.value if outcome.proposed else None},
                )
            if outcome.decision is None:
                continue
            d = outcome.decision
            decisions.append(d)
            self.audit.record(
                now_utc, self.engine.name, "decision", tid,
                {"decision_id": d.decision_id, "rule_id": d.rule_id,
                 "previous_state": d.previous_state.value, "state": d.state.value,
                 "evidence_event_ids": d.evidence_event_ids, "evidencia": summary.to_dict()},
            )
            alert = self.alerts.build(d, summary)
            if alert is None and self.alerts.last_suppressed is not None:
                self.audit.record(
                    now_utc, self.alerts.name, "alerta_suprimida", tid,
                    {"decision_id": d.decision_id, "state": d.state.value,
                     "motivo": self.alerts.last_suppressed},
                )
            if alert is not None:
                alerts.append(alert)
                self.audit.record(
                    now_utc, self.alerts.name, "alerta_informativa", alert.alert_id,
                    {"track_id": tid, "decision_id": d.decision_id, "state": d.state.value,
                     "severity": alert.severity},
                )

        self.audit.record(
            now_utc, PIPELINE_ACTOR, "lote_procesado", "lote",
            {"aceptadas": len(accepted), "rechazadas": len(rejected),
             "duplicados": len(duplicates), "decisiones": len(decisions),
             "alertas": len(alerts), "tracks": len(self.tracker.tracks),
             "tracks_modificados": sorted(touched), "dedup_purgados": pruned},
        )

        return PipelineResult(
            processed_at_utc=now_utc,
            accepted=accepted,
            rejected=rejected,
            duplicates_dropped=duplicates,
            tracks=self.current_tracks(),
            decisions=decisions,
            alerts=alerts,
            audit_events=self.audit.drain(),
        )

    # ------------------------------------------------------------ revisión humana
    def apply_human_review(
        self,
        track_id: str,
        new_state: DetectionState,
        reviewer: str,
        now_utc: datetime,
        note: Optional[str] = None,
    ) -> DecisionRecord:
        """Cambio de estado por revisión humana explícita (regla ``R-HUM-01``).

        Opcional: la revisión de alertas vive en ``Storage.review_alert``; este método
        permite que el motor refleje esa decisión si el orquestador lo desea.
        """
        track = self.tracker.tracks[track_id]
        decision = self.engine.human_review(track, new_state, reviewer, note, now_utc)
        self.audit.record(
            now_utc, f"operador:{reviewer}", "revision_humana", track_id,
            {"decision_id": decision.decision_id, "state": new_state.value, "note": note},
        )
        return decision

    def export_audit_jsonl(self, path) -> object:
        return self.audit.export_jsonl(path)
