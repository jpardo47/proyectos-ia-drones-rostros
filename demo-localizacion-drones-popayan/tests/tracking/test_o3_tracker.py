"""Tests del agent_tracker: geometría, fusión con incertidumbre, pérdidas."""
from __future__ import annotations

import pytest

from src.contracts import SensorType as ST
from src.decision_agents.config import PipelineConfig
from src.tracking.agent_tracker import TrackerAgent
from src.tracking.geo import haversine_m
from tests.decision_agents.o3_factories import LAT0, LON0, obs, offset, t


def test_haversine_known_values():
    assert haversine_m(0, 0, 0, 0) == 0
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)
    a = offset(LAT0, LON0, north_m=1000)
    assert haversine_m(LAT0, LON0, *a) == pytest.approx(1000, rel=5e-3)


def test_simultaneous_observations_weighted_by_uncertainty():
    tr = TrackerAgent(PipelineConfig())
    a = obs("a", sensor=ST.RADAR, object_id=None, uncertainty=10.0)
    b = obs("b", sensor=ST.OPTICAL, object_id=None, uncertainty=20.0,
            pos=offset(LAT0, LON0, north_m=50))
    track = tr.create_track(a)
    tr.add_observation(track, a, 0.9, t(1))
    tr.add_observation(track, b, 0.9, t(1))
    [pt] = track.points()
    # Peso 1/100 vs 1/400 -> 80 % / 20 %: 10 m al norte.
    assert haversine_m(LAT0, LON0, pt.latitude, pt.longitude) == pytest.approx(10, abs=0.2)
    assert pt.uncertainty_m == pytest.approx((1 / (1 / 100 + 1 / 400)) ** 0.5, abs=1e-3)
    assert pt.source_event_ids == ["a", "b"]


def test_missing_uncertainty_uses_default():
    cfg = PipelineConfig(default_uncertainty_m=42.0)
    tr = TrackerAgent(cfg)
    a = obs("a", sensor=ST.RADAR, object_id=None, uncertainty=None)
    track = tr.create_track(a)
    tr.add_observation(track, a, 0.9, t(1))
    assert track.points()[0].uncertainty_m == pytest.approx(42.0)


def test_positionless_observations_update_last_seen_without_points():
    tr = TrackerAgent(PipelineConfig())
    a = obs("ac1", sensor=ST.ACOUSTIC, object_id=None, pos=None)
    track = tr.create_track(a)
    tr.add_observation(track, a, 0.9, t(0))
    b = obs("rf1", sensor=ST.RF, object_id=None, pos=None, at=4)
    out = tr.add_observation(track, b, 0.9, t(4))
    assert not out.point_added
    assert track.to_track().points == []
    assert track.last_seen_utc == t(4)


def test_lost_after_timeout_and_reopen():
    tr = TrackerAgent(PipelineConfig(lost_timeout_s=10))
    a = obs("a")
    track = tr.create_track(a)
    tr.add_observation(track, a, 0.9, t(0))
    assert tr.update_lost(t(10)) == []
    assert tr.update_lost(t(10.5)) == [track.track_id]
    assert tr.update_lost(t(20)) == []  # ya estaba perdido
    out = tr.add_observation(track, obs("b", at=30), 0.9, t(31))
    assert out.reopened and not track.is_lost and track.segment_start_utc == t(30)


def test_mixing_simulated_and_real_raises():
    tr = TrackerAgent(PipelineConfig())
    a = obs("a", simulated=True)
    track = tr.create_track(a)
    with pytest.raises(ValueError):
        tr.add_observation(track, obs("b", simulated=False), 0.9, t(1))


def test_contradiction_is_recorded_and_not_added():
    tr = TrackerAgent(PipelineConfig())
    a = obs("a")
    track = tr.create_track(a)
    tr.add_observation(track, a, 0.9, t(0))
    out = tr.add_observation(track, obs("b", at=1, pos=offset(LAT0, LON0, east_m=1500)), 0.9, t(1))
    assert out.contradiction is not None and not out.point_added
    assert out.contradiction.reference_event_ids == ("a",)
    assert len(track.points()) == 1
    # Una posición plausible del mismo objeto sí se agrega.
    out = tr.add_observation(track, obs("c", at=2, pos=offset(LAT0, LON0, east_m=40)), 0.9, t(2))
    assert out.contradiction is None and out.point_added


def test_track_ids_are_deterministic():
    ids = []
    for _ in range(2):
        tr = TrackerAgent(PipelineConfig())
        ids.append(tr.create_track(obs("evento-x")).track_id)
    assert ids[0] == ids[1] and ids[0].startswith("TRK-SIM-")
