"""agent_evidence: resumen trazable de la evidencia de un track.

Solo cuenta lo que hay en las observaciones aceptadas (qué fuentes, cuántas, cuándo).
No infiere identidad, intención ni nada que no esté en los datos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.contracts import SensorType
from src.tracking.agent_tracker import TrackState

from .config import PipelineConfig

EVIDENCE_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourceEvidence:
    sensor_type: SensorType
    station_id: str
    count: int
    first_utc: datetime
    last_utc: datetime
    event_ids: tuple[str, ...]
    with_position: int


@dataclass(frozen=True)
class EvidenceSummary:
    track_id: str
    is_simulated: bool
    segment_start_utc: datetime
    total_observations: int
    valid_event_ids: tuple[str, ...]          # cuentan como evidencia válida
    low_score_event_ids: tuple[str, ...]      # classifier_score < mínimo
    conflicting_event_ids: tuple[str, ...]    # contradicciones registradas
    sources: tuple[SourceEvidence, ...]
    first_utc: Optional[datetime]
    last_utc: Optional[datetime]
    points_count: int

    @property
    def sensor_types(self) -> list[str]:
        return sorted({s.sensor_type.value for s in self.sources})

    @property
    def station_ids(self) -> list[str]:
        return sorted({s.station_id for s in self.sources})

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "is_simulated": self.is_simulated,
            "segment_start_utc": self.segment_start_utc.isoformat(),
            "total_observations": self.total_observations,
            "valid": len(self.valid_event_ids),
            "low_score": len(self.low_score_event_ids),
            "conflicting": len(self.conflicting_event_ids),
            "points": self.points_count,
            "sources": [
                {
                    "sensor_type": s.sensor_type.value,
                    "station_id": s.station_id,
                    "count": s.count,
                    "with_position": s.with_position,
                    "first_utc": s.first_utc.isoformat(),
                    "last_utc": s.last_utc.isoformat(),
                }
                for s in self.sources
            ],
        }

    def describe(self) -> str:
        """Descripción neutra en español (sin interpretación)."""
        if not self.sources:
            return "Sin observaciones en el segmento actual."
        parts = [
            f"{s.count} obs. {s.sensor_type.value} de {s.station_id}"
            + (f" ({s.with_position} con posición)" if s.with_position else " (sin posición)")
            for s in self.sources
        ]
        span = ""
        if self.first_utc and self.last_utc:
            span = (
                f" entre {self.first_utc.strftime('%H:%M:%S')} y "
                f"{self.last_utc.strftime('%H:%M:%S')} UTC"
            )
        return "; ".join(parts) + span + "."


class EvidenceAgent:
    name = "agent_evidence"
    version = EVIDENCE_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config

    def is_low_score(self, score: Optional[float]) -> bool:
        return score is not None and score < self.config.min_classifier_score

    def summarize(self, track: TrackState) -> EvidenceSummary:
        seg = track.segment_observations()
        groups: dict[tuple[str, str], list] = {}
        for to in seg:
            o = to.observation
            groups.setdefault((o.sensor_type.value, o.station_id), []).append(o)
        sources = []
        for (_, station), obs in sorted(groups.items()):
            ts = [o.timestamp_utc for o in obs]
            sources.append(
                SourceEvidence(
                    sensor_type=obs[0].sensor_type,
                    station_id=station,
                    count=len(obs),
                    first_utc=min(ts),
                    last_utc=max(ts),
                    event_ids=tuple(sorted(o.event_id for o in obs)),
                    with_position=sum(1 for o in obs if o.has_position),
                )
            )
        valid = sorted(
            to.observation.event_id
            for to in seg
            if not to.conflicting and not self.is_low_score(to.observation.classifier_score)
        )
        low = sorted(
            to.observation.event_id
            for to in seg
            if self.is_low_score(to.observation.classifier_score)
        )
        conflicting = sorted({c.event_id for c in track.segment_contradictions()})
        all_ts = [to.observation.timestamp_utc for to in seg]
        return EvidenceSummary(
            track_id=track.track_id,
            is_simulated=track.is_simulated,
            segment_start_utc=track.segment_start_utc,
            total_observations=len(seg),
            valid_event_ids=tuple(valid),
            low_score_event_ids=tuple(low),
            conflicting_event_ids=tuple(conflicting),
            sources=tuple(sources),
            first_utc=min(all_ts) if all_ts else None,
            last_utc=max(all_ts) if all_ts else None,
            points_count=len(track.contributions),
        )
