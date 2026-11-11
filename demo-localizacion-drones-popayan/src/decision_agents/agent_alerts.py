"""agent_alerts: alertas INFORMATIVAS para revisión humana.

- ``severity`` siempre ``"informativa"`` y ``requires_human_review`` siempre ``True``.
- Mensaje neutro: describe la evidencia y pide revisión humana. No usa lenguaje de
  amenaza ni hostilidad y no recomienda ninguna acción.
- Estados que generan alerta: ``REQUIERE_REVISION``, ``DETECCION_CORROBORADA``,
  ``SEGUIMIENTO_PERDIDO`` y, si ``alert_on_posible``, ``DETECCION_POSIBLE``.
- Proporcionalidad: (a) solo se alerta en CAMBIOS de estado (nunca por reconfirmar el
  mismo estado); (b) no se repite la alerta del mismo estado para el mismo track antes
  de ``alert_cooldown_s``; (c) con ``alert_lost_only_if_alerted`` la pérdida solo alerta
  si el track ya había generado alguna alerta. Las supresiones se auditan.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from src.contracts import Alert, DecisionRecord, DetectionState

from .agent_evidence import EvidenceSummary
from .config import PipelineConfig

ALERTS_VERSION = "1.0.0"

# Vocabulario que nunca debe aparecer en un mensaje de alerta (verificado en tests).
FORBIDDEN_TERMS = (
    "amenaza", "hostil", "enemigo", "ataque", "atacar", "intercept", "neutraliz",
    "derribar", "inhibir", "interferir", "peligro", "riesgo",
)

_STATE_TEXT = {
    DetectionState.DETECCION_POSIBLE: "Detección posible (una sola fuente)",
    DetectionState.DETECCION_CORROBORADA: "Detección corroborada por fuentes independientes",
    DetectionState.REQUIERE_REVISION: "Datos inconsistentes que requieren revisión",
    DetectionState.SEGUIMIENTO_PERDIDO: "Seguimiento perdido (sin observaciones recientes)",
}


class AlertsAgent:
    name = "agent_alerts"
    version = ALERTS_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config
        # (track_id, estado) -> instante de la última alerta emitida (proporcionalidad).
        self._last_alert: dict[tuple[str, DetectionState], datetime] = {}
        self.last_suppressed: Optional[str] = None

    def alert_states(self) -> set[DetectionState]:
        states = {
            DetectionState.REQUIERE_REVISION,
            DetectionState.DETECCION_CORROBORADA,
            DetectionState.SEGUIMIENTO_PERDIDO,
        }
        if self.config.alert_on_posible:
            states.add(DetectionState.DETECCION_POSIBLE)
        return states

    def build(self, decision: DecisionRecord, summary: Optional[EvidenceSummary]) -> Optional[Alert]:
        self.last_suppressed = None
        if decision.state not in self.alert_states():
            return None
        if (
            decision.state == DetectionState.SEGUIMIENTO_PERDIDO
            and self.config.alert_lost_only_if_alerted
            and not any(tid == decision.track_id for tid, _ in self._last_alert)
        ):
            self.last_suppressed = (
                "pérdida de un track que nunca generó alerta (p. ej. una sola detección "
                "posible): se registra la decisión sin alerta"
            )
            return None
        key = (decision.track_id, decision.state)
        prev = self._last_alert.get(key)
        if prev is not None and (
            decision.decided_at_utc - prev
        ).total_seconds() < self.config.alert_cooldown_s:
            self.last_suppressed = (
                f"ya se emitió una alerta {decision.state.value} para este track hace "
                f"{(decision.decided_at_utc - prev).total_seconds():.0f} s "
                f"(< {self.config.alert_cooldown_s:.0f} s)"
            )
            return None
        self._last_alert[key] = decision.decided_at_utc
        prefix = "[SIMULADO] " if decision.is_simulated else ""
        evidence_text = summary.describe() if summary is not None else ""
        message = (
            f"{prefix}{_STATE_TEXT[decision.state]} en el track {decision.track_id}. "
            f"Evidencia: {evidence_text} Regla {decision.rule_id}: {decision.reason} "
            "Alerta informativa: un operador debe revisar los datos."
        )
        alert_id = "ALR-" + hashlib.sha256(decision.decision_id.encode("utf-8")).hexdigest()[:16]
        return Alert(
            alert_id=alert_id,
            track_id=decision.track_id,
            state=decision.state,
            message=message,
            severity="informativa",
            requires_human_review=True,
            created_at_utc=decision.decided_at_utc,
            decision_id=decision.decision_id,
            is_simulated=decision.is_simulated,
        )
