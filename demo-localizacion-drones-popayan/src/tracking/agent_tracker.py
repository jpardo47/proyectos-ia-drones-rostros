"""agent_tracker: trayectorias con incertidumbre, pérdidas y reapariciones.

Reglas (todas deterministas y explicables):

- Cada observación aceptada y asociada a un track se guarda como EVIDENCIA.
- Solo las observaciones CON posición aportan puntos. Acústica y RF sin posición
  actualizan ``last_seen`` pero nunca generan puntos: un objeto solo acústico
  tiene ``Track.points == []``.
- Suavizado: observaciones del mismo instante exacto se fusionan con una media
  ponderada por ``1/sigma^2`` (sigma = ``measurement_uncertainty`` o el valor por
  defecto de la configuración). La incertidumbre fusionada es ``sqrt(1/sum(1/sigma^2))``.
  Dos contribuciones del mismo tipo de sensor con la misma posición en el mismo
  instante (p. ej. el MISMO mensaje Remote ID recibido por dos estaciones) cuentan
  una sola vez: no son mediciones independientes y no reducen la incertidumbre.
- Contradicción: si una observación con el MISMO ``object_id`` del track cae a más de
  ``max(contradiction_distance_m, k*sigma_comb + v_max*|dt|)`` del punto del track
  más cercano en el tiempo (dentro de ``correlation_window_s``), se registra como
  contradicción y NO se agrega a la trayectoria.
- Pérdida: sin observaciones durante más de ``lost_timeout_s`` respecto a ``now_utc``.
- Reaparición: una observación reciente (``now - t <= lost_timeout_s``) asociada a un
  track perdido lo reabre y comienza un nuevo SEGMENTO de evidencia.
"""
from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.contracts import (
    AltitudeReference,
    DetectionState,
    Observation,
    SensorType,
    Track,
    TrackPoint,
)
from src.decision_agents.config import PipelineConfig

from .geo import combined_sigma, haversine_m

TRACKER_VERSION = "1.0.0"


@dataclass(frozen=True)
class Contribution:
    event_id: str
    sensor_type: SensorType
    station_id: str
    latitude: float
    longitude: float
    altitude: Optional[float]
    altitude_reference: Optional[AltitudeReference]
    sigma_m: float


@dataclass
class TrackedObservation:
    observation: Observation
    quality: float
    point_added: bool
    conflicting: bool = False


@dataclass(frozen=True)
class Contradiction:
    event_id: str
    reference_event_ids: tuple[str, ...]
    distance_m: float
    threshold_m: float
    timestamp_utc: datetime


@dataclass(frozen=True)
class AddOutcome:
    point_added: bool
    contradiction: Optional[Contradiction]
    reopened: bool


@dataclass
class TrackState:
    """Estado interno mutable de un track (no se expone fuera del pipeline)."""

    track_id: str
    object_id: Optional[str]
    is_simulated: bool
    first_seen_utc: datetime
    last_seen_utc: datetime
    segment_start_utc: datetime
    observations: list[TrackedObservation] = field(default_factory=list)
    contributions: dict[datetime, list[Contribution]] = field(default_factory=dict)
    contradictions: list[Contradiction] = field(default_factory=list)
    is_lost: bool = False
    state: DetectionState = DetectionState.SIN_OBSERVACION
    reopen_count: int = 0
    # Track de "presencia": (station_id, sensor_type, is_simulated) para observaciones
    # anónimas SIN posición. Nunca tiene puntos ni se asocia espacialmente.
    presence_key: Optional[tuple[str, str, bool]] = None
    _ts_sorted: list[datetime] = field(default_factory=list, repr=False)
    _point_cache: dict[datetime, TrackPoint] = field(default_factory=dict, repr=False)
    _stream_ts: set[tuple[str, str, datetime]] = field(default_factory=set, repr=False)

    def add_contribution(self, c: "Contribution", ts: datetime) -> None:
        if ts not in self.contributions:
            self.contributions[ts] = []
            bisect.insort(self._ts_sorted, ts)
        self.contributions[ts].append(c)
        self._point_cache.pop(ts, None)

    # ------------------------------------------------------------------ puntos
    def fused_point(self, ts: datetime) -> Optional[TrackPoint]:
        cached = self._point_cache.get(ts)
        if cached is not None:
            return cached
        contribs = self.contributions.get(ts)
        if not contribs:
            return None
        # Colapsa contribuciones idénticas del mismo tipo de sensor (misma autodeclaración).
        unique: dict[tuple, Contribution] = {}
        for c in contribs:
            key = (c.sensor_type.value, round(c.latitude, 7), round(c.longitude, 7))
            prev = unique.get(key)
            if prev is None or (c.sigma_m, c.event_id) < (prev.sigma_m, prev.event_id):
                unique[key] = c
        weights = [(1.0 / (c.sigma_m * c.sigma_m), c) for c in unique.values()]
        wsum = sum(w for w, _ in weights)
        lat = sum(w * c.latitude for w, c in weights) / wsum
        lon = sum(w * c.longitude for w, c in weights) / wsum
        sigma = (1.0 / wsum) ** 0.5
        with_alt = sorted(
            (c for c in contribs if c.altitude is not None), key=lambda c: (c.sigma_m, c.event_id)
        )
        alt = with_alt[0].altitude if with_alt else None
        alt_ref = with_alt[0].altitude_reference if with_alt else None
        point = TrackPoint(
            timestamp_utc=ts,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            altitude_reference=alt_ref,
            uncertainty_m=round(sigma, 3),
            source_event_ids=sorted({c.event_id for c in contribs}),
        )
        self._point_cache[ts] = point
        return point

    def points(self) -> list[TrackPoint]:
        return [p for ts in self._ts_sorted if (p := self.fused_point(ts)) is not None]

    def has_points(self) -> bool:
        return bool(self.contributions)

    def nearest_point(self, ts: datetime, window_s: float) -> Optional[tuple[TrackPoint, float]]:
        """Punto fusionado más cercano en el tiempo dentro de la ventana -> (punto, |dt| s)."""
        best: Optional[tuple[float, datetime]] = None
        i = bisect.bisect_left(self._ts_sorted, ts)
        for j in (i - 1, i):  # vecinos inmediatos en el tiempo (anterior y posterior)
            if 0 <= j < len(self._ts_sorted):
                pts = self._ts_sorted[j]
                dt = abs((pts - ts).total_seconds())
                if dt <= window_s and (best is None or (dt, pts) < best):
                    best = (dt, pts)
        if best is None:
            return None
        point = self.fused_point(best[1])
        assert point is not None
        return point, best[0]

    # --------------------------------------------------------------- evidencia
    def segment_observations(self) -> list[TrackedObservation]:
        return [
            o for o in self.observations if o.observation.timestamp_utc >= self.segment_start_utc
        ]

    def segment_contradictions(self) -> list[Contradiction]:
        return [c for c in self.contradictions if c.timestamp_utc >= self.segment_start_utc]

    def has_simultaneous(self, station_id: str, sensor_type: SensorType, ts: datetime) -> bool:
        return (station_id, sensor_type.value, ts) in self._stream_ts

    def to_track(self) -> Track:
        obs = [o.observation for o in self.observations]
        return Track(
            track_id=self.track_id,
            object_id=self.object_id,
            points=self.points(),
            first_seen_utc=self.first_seen_utc,
            last_seen_utc=self.last_seen_utc,
            station_ids=sorted({o.station_id for o in obs}),
            sensor_types=sorted({o.sensor_type for o in obs}, key=lambda s: s.value),
            is_lost=self.is_lost,
            is_simulated=self.is_simulated,
        )


class TrackerAgent:
    name = "agent_tracker"
    version = TRACKER_VERSION

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.tracks: dict[str, TrackState] = {}
        self.by_object: dict[tuple[str, bool], str] = {}
        self.by_presence: dict[tuple[str, str, bool], str] = {}

    # ---------------------------------------------------------------- creación
    def _new_track_id(self, first: Observation) -> str:
        prefix = "TRK-SIM-" if first.is_simulated else "TRK-"
        base = hashlib.sha256(
            f"{first.event_id}|{first.is_simulated}".encode("utf-8")
        ).hexdigest()[:12]
        track_id = prefix + base
        n = 1
        while track_id in self.tracks:  # colisión improbable: sufijo determinista
            n += 1
            track_id = f"{prefix}{base}-{n}"
        return track_id

    def create_track(self, obs: Observation, presence: bool = False) -> TrackState:
        track = TrackState(
            track_id=self._new_track_id(obs),
            object_id=obs.object_id,
            is_simulated=obs.is_simulated,
            first_seen_utc=obs.timestamp_utc,
            last_seen_utc=obs.timestamp_utc,
            segment_start_utc=obs.timestamp_utc,
        )
        self.tracks[track.track_id] = track
        if presence:
            if obs.object_id is not None or obs.has_position:
                raise ValueError("un track de presencia solo admite observaciones anónimas sin posición")
            track.presence_key = (obs.station_id, obs.sensor_type.value, obs.is_simulated)
            self.by_presence[track.presence_key] = track.track_id
        if obs.object_id is not None:
            self.by_object[(obs.object_id, obs.is_simulated)] = track.track_id
        return track

    # ------------------------------------------------------------- incorporar
    def sigma_of(self, obs: Observation) -> float:
        if obs.measurement_uncertainty is not None and obs.measurement_uncertainty > 0:
            return float(obs.measurement_uncertainty)
        return self.config.default_uncertainty_m

    def add_observation(
        self, track: TrackState, obs: Observation, quality: float, now_utc: datetime
    ) -> AddOutcome:
        if obs.is_simulated != track.is_simulated:  # defensa en profundidad
            raise ValueError("no se mezclan observaciones simuladas y no simuladas en un track")
        cfg = self.config
        sigma = self.sigma_of(obs)
        contradiction: Optional[Contradiction] = None
        point_added = False

        reopened = False
        if track.is_lost and (now_utc - obs.timestamp_utc).total_seconds() <= cfg.lost_timeout_s:
            track.is_lost = False
            track.segment_start_utc = obs.timestamp_utc
            track.reopen_count += 1
            reopened = True

        if obs.has_position:
            assert obs.latitude is not None and obs.longitude is not None
            if track.object_id is not None and obs.object_id == track.object_id:
                near = track.nearest_point(obs.timestamp_utc, cfg.correlation_window_s)
                if near is not None:
                    point, dt = near
                    d = haversine_m(point.latitude, point.longitude, obs.latitude, obs.longitude)
                    gate = (
                        cfg.association_sigma_factor
                        * combined_sigma(sigma, point.uncertainty_m or cfg.default_uncertainty_m)
                        + cfg.max_speed_mps * dt
                    )
                    threshold = max(cfg.contradiction_distance_m, gate)
                    if d > threshold:
                        contradiction = Contradiction(
                            event_id=obs.event_id,
                            reference_event_ids=tuple(point.source_event_ids),
                            distance_m=round(d, 1),
                            threshold_m=round(threshold, 1),
                            timestamp_utc=obs.timestamp_utc,
                        )
                        track.contradictions.append(contradiction)
            if contradiction is None:
                track.add_contribution(
                    Contribution(
                        event_id=obs.event_id,
                        sensor_type=obs.sensor_type,
                        station_id=obs.station_id,
                        latitude=obs.latitude,
                        longitude=obs.longitude,
                        altitude=obs.altitude,
                        altitude_reference=obs.altitude_reference,
                        sigma_m=sigma,
                    ),
                    obs.timestamp_utc,
                )
                point_added = True

        track._stream_ts.add((obs.station_id, obs.sensor_type.value, obs.timestamp_utc))
        track.observations.append(
            TrackedObservation(
                observation=obs,
                quality=quality,
                point_added=point_added,
                conflicting=contradiction is not None,
            )
        )
        if obs.timestamp_utc > track.last_seen_utc:
            track.last_seen_utc = obs.timestamp_utc
        if obs.timestamp_utc < track.first_seen_utc:
            track.first_seen_utc = obs.timestamp_utc
        return AddOutcome(point_added=point_added, contradiction=contradiction, reopened=reopened)

    # ----------------------------------------------------------------- pérdida
    def update_lost(self, now_utc: datetime) -> list[str]:
        newly_lost: list[str] = []
        for track_id in sorted(self.tracks):
            track = self.tracks[track_id]
            if track.is_lost:
                continue
            if (now_utc - track.last_seen_utc).total_seconds() > self.config.lost_timeout_s:
                track.is_lost = True
                newly_lost.append(track_id)
        return newly_lost

    def snapshot(self) -> list[Track]:
        return [self.tracks[tid].to_track() for tid in sorted(self.tracks)]
