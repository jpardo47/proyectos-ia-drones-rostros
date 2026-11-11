"""agent_correlator: deduplicación y asociación CONSERVADORA de observaciones a tracks.

Deduplicación
- Por ``event_id`` ya visto (en este lote o en lotes anteriores, dentro de la retención).
- Por contenido equivalente: misma estación, tipo de sensor, ``object_id``, instante
  exacto y posición (lat/lon redondeadas, altitud). Cambia el ``event_id`` pero es la
  misma medición repetida.

Asociación (ante la duda, NO asociar):
1. Con ``object_id``: solo al track con el MISMO ``object_id`` y el mismo
   ``is_simulated`` (incluido uno perdido: reaparición). Si no existe, track nuevo.
2. Sin ``object_id`` y con posición: candidatos = tracks activos (no de presencia) con
   el mismo ``is_simulated`` cuyo punto más cercano en el tiempo esté a
   ``|dt| <= association_max_gap_s`` y a una distancia
   ``d <= puerta = min(max_association_distance_m, k*sqrt(s_obs^2+s_pt^2) + v_max*|dt|)``,
   excluyendo los que ya tienen una observación de la MISMA estación y tipo de sensor en
   el MISMO instante (un sensor no reporta dos veces el mismo objeto a la vez).
   - 0 candidatos -> track nuevo;
   - 1 candidato  -> se asocia;
   - >1 candidatos -> se ordenan por ``z = d/puerta``; se asocia al mejor solo si
     ``z1 < ambiguity_ratio * z2`` (claramente mejor). Si no, la observación se acepta
     pero queda SIN asociar (no se elige arbitrariamente ni se crea track nuevo, para no
     fragmentar). Se audita como ``observacion_no_asociada``.
3. Sin ``object_id`` y sin posición (acústica, RF): track de PRESENCIA único por
   (estación, tipo de sensor, procedencia). Nunca se asocia espacialmente ni a tracks
   con posición; ``points`` siempre vacío. Si caduca y vuelven a llegar observaciones
   recientes, el mismo track se reabre.
Nunca se mezclan observaciones simuladas y no simuladas en un mismo track.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Optional

from src.contracts import Observation
from src.decision_agents.config import PipelineConfig
from src.tracking.agent_tracker import TrackState
from src.tracking.geo import combined_sigma, haversine_m

CORRELATOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class DuplicateCheck:
    is_duplicate: bool
    reason_code: Optional[str] = None      # DUPLICATE_EVENT_ID | DUPLICATE_CONTENT
    original_event_id: Optional[str] = None


@dataclass(frozen=True)
class Association:
    track_id: Optional[str]                # None -> crear track nuevo
    method: str                            # object_id | espacial | corriente_sin_posicion | nuevo
    reason: str
    candidate_track_ids: tuple[str, ...] = field(default_factory=tuple)
    ambiguous: bool = False
    create_track: bool = True              # False -> aceptada pero sin asociar (ambigua)
    presence: bool = False                 # crear track de presencia (sin posición)


class CorrelatorAgent:
    name = "agent_correlator"
    version = CORRELATOR_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config
        self._seen_event_ids: dict[str, datetime] = {}
        self._seen_content: dict[tuple, tuple[str, datetime]] = {}

    # ----------------------------------------------------------- duplicados
    def content_key(self, obs: Observation) -> tuple:
        nd = self.config.position_round_decimals
        return (
            obs.station_id,
            obs.sensor_type.value,
            obs.object_id,
            obs.timestamp_utc.isoformat(),
            None if obs.latitude is None else round(obs.latitude, nd),
            None if obs.longitude is None else round(obs.longitude, nd),
            None if obs.altitude is None else round(obs.altitude, 1),
            obs.is_simulated,
        )

    def check_duplicate(self, obs: Observation) -> DuplicateCheck:
        if obs.event_id in self._seen_event_ids:
            return DuplicateCheck(True, "DUPLICATE_EVENT_ID", obs.event_id)
        prev = self._seen_content.get(self.content_key(obs))
        if prev is not None:
            return DuplicateCheck(True, "DUPLICATE_CONTENT", prev[0])
        return DuplicateCheck(False)

    def register(self, obs: Observation) -> None:
        self._seen_event_ids[obs.event_id] = obs.timestamp_utc
        self._seen_content[self.content_key(obs)] = (obs.event_id, obs.timestamp_utc)

    def prune(self, now_utc: datetime) -> int:
        limit = now_utc - timedelta(seconds=self.config.dedup_retention_s)
        old_ids = [k for k, ts in self._seen_event_ids.items() if ts < limit]
        for k in old_ids:
            del self._seen_event_ids[k]
        old_keys = [k for k, (_, ts) in self._seen_content.items() if ts < limit]
        for k in old_keys:
            del self._seen_content[k]
        return len(old_ids)

    # ------------------------------------------------------------ asociación
    def associate(
        self,
        obs: Observation,
        tracks: Mapping[str, TrackState],
        by_object: Mapping[tuple[str, bool], str],
        sigma_obs: float,
        presence: Optional[Mapping[tuple[str, str, bool], str]] = None,
    ) -> Association:
        presence = presence or {}
        cfg = self.config
        if obs.object_id is not None:
            tid = by_object.get((obs.object_id, obs.is_simulated))
            if tid is not None:
                return Association(tid, "object_id", "mismo object_id e igual procedencia", (tid,))
            return Association(None, "nuevo", "object_id sin track previo: se crea uno nuevo")

        if obs.has_position:
            assert obs.latitude is not None and obs.longitude is not None
            scored: list[tuple[float, str, float, float]] = []   # (z, track_id, d, gate)
            for tid in sorted(tracks):
                t = tracks[tid]
                if t.is_lost or t.is_simulated != obs.is_simulated or t.presence_key is not None:
                    continue
                if t.has_simultaneous(obs.station_id, obs.sensor_type, obs.timestamp_utc):
                    continue
                near = t.nearest_point(obs.timestamp_utc, cfg.association_max_gap_s)
                if near is None:
                    continue
                point, dt = near
                d = haversine_m(point.latitude, point.longitude, obs.latitude, obs.longitude)
                gate = min(
                    cfg.max_association_distance_m,
                    cfg.association_sigma_factor
                    * combined_sigma(sigma_obs, point.uncertainty_m or cfg.default_uncertainty_m)
                    + cfg.max_speed_mps * dt,
                )
                if d <= gate:
                    scored.append((d / gate, tid, d, gate))
            scored.sort()
            cands = tuple(tid for _, tid, _, _ in scored)
            if len(scored) == 1:
                return Association(
                    scored[0][1], "espacial", "único track compatible en espacio y tiempo", cands
                )
            if len(scored) > 1:
                z1, z2 = scored[0][0], scored[1][0]
                if z1 < cfg.ambiguity_ratio * z2:
                    return Association(
                        scored[0][1], "espacial_mejor_candidato",
                        f"varios candidatos; el mejor (d/puerta={z1:.2f}) es claramente mejor que "
                        f"el segundo ({z2:.2f})",
                        cands,
                    )
                return Association(
                    None, "no_asociada",
                    f"asociación ambigua (d/puerta {z1:.2f} vs {z2:.2f}): la observación queda "
                    "sin asociar; no se crea track nuevo",
                    cands, ambiguous=True, create_track=False,
                )
            return Association(None, "nuevo", "sin track compatible en espacio y tiempo")

        # Sin object_id y sin posición: track de PRESENCIA por (estación, tipo, procedencia).
        key = (obs.station_id, obs.sensor_type.value, obs.is_simulated)
        tid = presence.get(key)
        if tid is not None:
            return Association(
                tid, "presencia",
                "observación sin posición: se agrupa en el track de presencia de la misma "
                "estación y tipo de sensor",
                (tid,),
            )
        return Association(
            None, "nuevo_presencia",
            "observación sin posición ni object_id: se abre el track de presencia de la "
            "estación y tipo de sensor",
            presence=True,
        )
