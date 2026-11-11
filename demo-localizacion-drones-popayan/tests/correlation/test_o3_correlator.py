"""Tests del agent_correlator: duplicados y asociación conservadora."""
from __future__ import annotations

from src.contracts import SensorType as ST
from src.correlation.agent_correlator import CorrelatorAgent
from src.decision_agents.config import PipelineConfig
from src.decision_agents.pipeline import OperationalPipeline
from src.tracking.agent_tracker import TrackerAgent
from tests.decision_agents.o3_factories import LAT0, LON0, obs, offset, t


def _setup():
    cfg = PipelineConfig()
    return cfg, CorrelatorAgent(cfg), TrackerAgent(cfg)


def _add(corr, tracker, o, now):
    assoc = corr.associate(o, tracker.tracks, tracker.by_object, tracker.sigma_of(o),
                           tracker.by_presence)
    corr.register(o)
    if assoc.track_id is None and not assoc.create_track:
        return assoc, None
    if assoc.track_id is None:
        track = tracker.create_track(o, presence=assoc.presence)
    else:
        track = tracker.tracks[assoc.track_id]
    tracker.add_observation(track, o, 0.9, now)
    return assoc, track


def test_agent_metadata():
    _, corr, tracker = _setup()
    assert corr.name == "agent_correlator" and corr.version
    assert tracker.name == "agent_tracker" and tracker.version


def test_duplicate_by_event_id_and_content():
    _, corr, _ = _setup()
    a = obs("e1")
    assert not corr.check_duplicate(a).is_duplicate
    corr.register(a)
    d1 = corr.check_duplicate(obs("e1", at=9))
    assert d1.is_duplicate and d1.reason_code == "DUPLICATE_EVENT_ID"
    d2 = corr.check_duplicate(obs("otro-id"))
    assert d2.is_duplicate and d2.reason_code == "DUPLICATE_CONTENT" and d2.original_event_id == "e1"
    # Otra estación con el mismo contenido NO es duplicado (es otra recepción).
    assert not corr.check_duplicate(obs("e2", station="EST-SIM-02")).is_duplicate
    # Otra posición tampoco.
    assert not corr.check_duplicate(obs("e3", pos=offset(LAT0, LON0, north_m=5))).is_duplicate


def test_dedup_memory_pruned_after_retention():
    cfg = PipelineConfig(dedup_retention_s=60)
    corr = CorrelatorAgent(cfg)
    corr.register(obs("e1", at=0))
    assert corr.prune(t(30)) == 0 and corr.check_duplicate(obs("e1")).is_duplicate
    assert corr.prune(t(61)) == 1 and not corr.check_duplicate(obs("e1")).is_duplicate


def test_object_id_association_only_same_id():
    _, corr, tracker = _setup()
    _, tr1 = _add(corr, tracker, obs("a1", object_id="UAS-1"), t(0))
    assoc, tr2 = _add(corr, tracker, obs("b1", object_id="UAS-2", at=1), t(1))
    assert assoc.track_id is None and tr1.track_id != tr2.track_id
    assoc, tr3 = _add(corr, tracker, obs("a2", object_id="UAS-1", at=2), t(2))
    assert assoc.method == "object_id" and tr3.track_id == tr1.track_id


def test_spatial_association_requires_compatibility():
    _, corr, tracker = _setup()
    _, tr1 = _add(corr, tracker, obs("r1", sensor=ST.RADAR, object_id=None), t(0))
    near = offset(LAT0, LON0, east_m=25)
    assoc, _ = _add(corr, tracker, obs("r2", sensor=ST.RADAR, object_id=None, at=1, pos=near), t(1))
    assert assoc.track_id == tr1.track_id and assoc.method == "espacial"
    far = offset(LAT0, LON0, east_m=900)
    assoc, tr3 = _add(corr, tracker, obs("r3", sensor=ST.RADAR, object_id=None, at=2, pos=far), t(2))
    assert assoc.track_id is None and tr3.track_id != tr1.track_id
    # Hueco mayor que association_max_gap_s (30 s): no se asocia aunque esté en el mismo sitio.
    assoc, _ = _add(corr, tracker, obs("r4", sensor=ST.RADAR, object_id=None, at=40), t(40))
    assert assoc.track_id is None


def test_ambiguous_association_leaves_observation_unassociated():
    _, corr, tracker = _setup()
    # A y B a 70 m entre sí (fuera de la puerta de 3*sqrt(10^2+10^2) ~ 42 m): dos tracks.
    a = offset(LAT0, LON0, east_m=-35)
    b = offset(LAT0, LON0, east_m=35)
    _add(corr, tracker, obs("A", sensor=ST.RADAR, station="EST-SIM-01", object_id=None, pos=a), t(0))
    _add(corr, tracker, obs("B", sensor=ST.OPTICAL, station="EST-SIM-02", object_id=None, pos=b), t(0))
    assoc, _ = _add(
        corr, tracker,
        obs("C", sensor=ST.RF, station="EST-SIM-03", object_id=None, pos=(LAT0, LON0), at=0.5),
        t(1),
    )
    assert assoc.track_id is None and assoc.ambiguous and len(assoc.candidate_track_ids) == 2
    assert not assoc.create_track and assoc.method == "no_asociada"
    assert len(tracker.tracks) == 2  # ni elección arbitraria ni track nuevo


def test_clearly_better_candidate_is_chosen():
    _, corr, tracker = _setup()
    a = offset(LAT0, LON0, east_m=-35)
    b = offset(LAT0, LON0, east_m=35)
    _, ta = _add(corr, tracker, obs("A", sensor=ST.RADAR, station="EST-SIM-01", object_id=None, pos=a), t(0))
    _add(corr, tracker, obs("B", sensor=ST.OPTICAL, station="EST-SIM-02", object_id=None, pos=b), t(0))
    # A 20 m de A y 50 m de B (ambos dentro de la puerta ~57 m): z_A=0.35 < 0.5*z_B=0.44.
    assoc, tr = _add(corr, tracker, obs("C", sensor=ST.RF, station="EST-SIM-03", object_id=None,
                                        pos=offset(LAT0, LON0, east_m=-15), at=0.5), t(1))
    assert assoc.method == "espacial_mejor_candidato" and tr.track_id == ta.track_id
    assert len(assoc.candidate_track_ids) == 2


def test_same_sensor_simultaneous_targets_are_not_merged():
    _, corr, tracker = _setup()
    _add(corr, tracker, obs("r1", sensor=ST.RADAR, object_id=None), t(0))
    assoc, _ = _add(
        corr, tracker,
        obs("r2", sensor=ST.RADAR, object_id=None, pos=offset(LAT0, LON0, north_m=30)), t(0),
    )
    assert assoc.track_id is None and len(tracker.tracks) == 2


def test_positionless_stream_association():
    _, corr, tracker = _setup()
    _, tr1 = _add(corr, tracker, obs("ac1", sensor=ST.ACOUSTIC, object_id=None, pos=None), t(0))
    assoc, _ = _add(corr, tracker, obs("ac2", sensor=ST.ACOUSTIC, object_id=None, pos=None, at=2), t(2))
    assert assoc.track_id == tr1.track_id and assoc.method == "presencia"
    assert tr1.presence_key == ("EST-SIM-01", "acoustic", True)
    # Mismo instante (dos fuentes oídas a la vez) y tras un hueco largo: mismo track.
    assoc, _ = _add(corr, tracker, obs("ac2b", sensor=ST.ACOUSTIC, object_id=None, pos=None,
                                       at=2, score=0.5), t(2))
    assert assoc.track_id == tr1.track_id
    assoc, _ = _add(corr, tracker, obs("ac9", sensor=ST.ACOUSTIC, object_id=None, pos=None,
                                       at=25), t(25))
    assert assoc.track_id == tr1.track_id
    # Otro detector (otra estación) no se mezcla con esa presencia.
    assoc, _ = _add(corr, tracker, obs("ac3", sensor=ST.ACOUSTIC, station="EST-SIM-05",
                                       object_id=None, pos=None, at=2), t(2))
    assert assoc.track_id is None and assoc.presence
    # Una observación con posición nunca se asocia a un track de presencia.
    assoc, _ = _add(corr, tracker, obs("rad", sensor=ST.RADAR, object_id=None, at=3), t(3))
    assert assoc.method == "nuevo"


def test_simulated_and_real_never_associated():
    _, corr, tracker = _setup()
    _, sim = _add(corr, tracker, obs("s1", sensor=ST.RADAR, object_id=None, simulated=True), t(0))
    assoc, real = _add(corr, tracker, obs("r1", sensor=ST.OPTICAL, object_id=None,
                                          simulated=False, at=0.5), t(1))
    assert assoc.track_id is None and sim.track_id != real.track_id
    assoc, _ = _add(corr, tracker, obs("r2", object_id="UAS-SIM-0001", simulated=False), t(1))
    assert assoc.track_id is None  # mismo object_id pero distinta procedencia


def test_pipeline_drops_duplicates_across_batches():
    p = OperationalPipeline()
    p.process_batch([obs("e1")], now_utc=t(1))
    r = p.process_batch([obs("e1"), obs("e1-copia")], now_utc=t(2))
    assert r.duplicates_dropped == ["e1", "e1-copia"]
