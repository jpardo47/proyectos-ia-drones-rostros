"""Tests deterministas del motor de estados de O3 (observaciones construidas a mano)."""
from __future__ import annotations

import json

import pytest

from src.contracts import DetectionState as S
from src.contracts import SensorType as ST
from src.contracts import StationStatus
from src.decision_agents.agent_alerts import FORBIDDEN_TERMS
from src.decision_agents.pipeline import ENGINE_VERSION, OperationalPipeline, PipelineConfig
from src.decision_agents.state_engine import ALLOWED_TRANSITIONS, rules_table
from tests.decision_agents.o3_factories import LAT0, LON0, obs, offset, t


def only_track(result):
    assert len(result.tracks) == 1, [tr.track_id for tr in result.tracks]
    return result.tracks[0]


def check_invariants(result):
    for d in result.decisions:
        assert d.rule_id and d.rule_id.startswith("R-")
        assert d.reason.strip()
        assert d.evidence_event_ids, d
        assert d.engine_version == ENGINE_VERSION
        assert d.state in ALLOWED_TRANSITIONS[d.previous_state]
    for a in result.alerts:
        assert a.severity == "informativa"
        assert a.requires_human_review is True
        low = a.message.lower()
        for term in FORBIDDEN_TERMS:
            assert term not in low, (term, a.message)
        assert "revis" in low


# --------------------------------------------------------------------- básicos

def test_single_valid_observation_is_posible():
    p = OperationalPipeline()
    r = p.process_batch([obs("e1")], now_utc=t(1))
    tr = only_track(r)
    assert p.current_states()[tr.track_id] == S.DETECCION_POSIBLE
    assert len(r.decisions) == 1
    d = r.decisions[0]
    assert (d.previous_state, d.state, d.rule_id) == (S.SIN_OBSERVACION, S.DETECCION_POSIBLE, "R-POS-01")
    assert d.evidence_event_ids == ["e1"]
    assert r.alerts == []  # alert_on_posible=False por defecto
    assert tr.is_simulated and tr.track_id.startswith("TRK-SIM-")
    check_invariants(r)


def test_posible_alert_when_configured():
    p = OperationalPipeline(PipelineConfig(alert_on_posible=True))
    r = p.process_batch([obs("e1")], now_utc=t(1))
    assert len(r.alerts) == 1 and r.alerts[0].state == S.DETECCION_POSIBLE
    assert r.alerts[0].message.startswith("[SIMULADO]")
    check_invariants(r)


def test_two_independent_consistent_sources_corroborate():
    p = OperationalPipeline()
    near = offset(LAT0, LON0, north_m=20)
    r1 = p.process_batch([obs("rid-1", at=0)], now_utc=t(0.5))
    assert r1.decisions[0].state == S.DETECCION_POSIBLE
    r2 = p.process_batch(
        [obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", at=1, object_id=None, pos=near,
             uncertainty=15)],
        now_utc=t(1.5),
    )
    tr = only_track(r2)
    assert set(tr.sensor_types) == {ST.REMOTE_ID, ST.RADAR}
    assert len(r2.decisions) == 1
    d = r2.decisions[0]
    assert (d.previous_state, d.state, d.rule_id) == (
        S.DETECCION_POSIBLE, S.DETECCION_CORROBORADA, "R-CORR-01")
    assert sorted(d.evidence_event_ids) == ["rad-1", "rid-1"]
    assert d.requires_human_review
    assert len(r2.alerts) == 1 and r2.alerts[0].state == S.DETECCION_CORROBORADA
    check_invariants(r2)


def test_same_remote_id_received_by_two_stations_stays_posible():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rid-A", station="EST-SIM-01", at=0), obs("rid-B", station="EST-SIM-02", at=0)],
        now_utc=t(1),
    )
    tr = only_track(r)
    assert tr.station_ids == ["EST-SIM-01", "EST-SIM-02"]
    assert p.current_states()[tr.track_id] == S.DETECCION_POSIBLE
    assert all(d.state != S.DETECCION_CORROBORADA for d in r.decisions)
    # La misma autodeclaración no reduce la incertidumbre del punto.
    assert len(tr.points) == 1 and tr.points[0].uncertainty_m == pytest.approx(10.0)
    # Ni en modo "distinta estación" dos Remote ID cuentan como independientes.
    p2 = OperationalPipeline(PipelineConfig(independence_mode="sensor_type_or_station"))
    r2 = p2.process_batch(
        [obs("rid-A", station="EST-SIM-01", at=0), obs("rid-B", station="EST-SIM-02", at=0)],
        now_utc=t(1),
    )
    assert list(p2.current_states().values()) == [S.DETECCION_POSIBLE]
    check_invariants(r2)


def test_same_type_different_station_only_in_station_mode():
    a = obs("rad-1", sensor=ST.RADAR, station="EST-SIM-01", object_id=None)
    b = obs("rad-2", sensor=ST.RADAR, station="EST-SIM-02", object_id=None,
            pos=offset(LAT0, LON0, east_m=15))
    p = OperationalPipeline()
    p.process_batch([a, b], now_utc=t(1))
    assert list(p.current_states().values()) == [S.DETECCION_POSIBLE]
    p2 = OperationalPipeline(PipelineConfig(independence_mode="sensor_type_or_station"))
    p2.process_batch([a, b], now_utc=t(1))
    assert list(p2.current_states().values()) == [S.DETECCION_CORROBORADA]


def test_non_independent_pair_configuration_blocks_corroboration():
    cfg = PipelineConfig(non_independent_sensor_pairs=[("remote_id", "rf")])
    p = OperationalPipeline(cfg)
    p.process_batch([obs("rid-1"), obs("rf-1", sensor=ST.RF, pos=None)], now_utc=t(1))
    assert list(p.current_states().values()) == [S.DETECCION_POSIBLE]


def test_contradictory_positions_require_review():
    p = OperationalPipeline()
    far = offset(LAT0, LON0, north_m=2000)
    r = p.process_batch([obs("rid-1", at=0), obs("rid-2", at=1, pos=far)], now_utc=t(2))
    tr = only_track(r)
    assert p.current_states()[tr.track_id] == S.REQUIERE_REVISION
    d = r.decisions[-1]
    assert d.rule_id == "R-REV-01" and d.requires_human_review
    assert set(d.evidence_event_ids) == {"rid-1", "rid-2"}
    # El punto incompatible no se agrega a la trayectoria.
    assert [pt.source_event_ids for pt in tr.points] == [["rid-1"]]
    assert len(r.alerts) == 1 and r.alerts[0].state == S.REQUIERE_REVISION
    # REQUIERE_REVISION no se rebaja sola aunque llegue evidencia independiente.
    r2 = p.process_batch(
        [obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", at=2, object_id=None)], now_utc=t(3)
    )
    assert p.current_states()[tr.track_id] == S.REQUIERE_REVISION
    check_invariants(r)
    check_invariants(r2)


def test_contradiction_with_corroborating_sensor_is_not_corroboration():
    """Una fuente independiente consistente no 'gana' a una contradicción."""
    p = OperationalPipeline()
    far = offset(LAT0, LON0, east_m=3000)
    r = p.process_batch(
        [obs("rid-1", at=0), obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", at=0.5,
                                 object_id=None),
         obs("rid-2", at=1, pos=far)],
        now_utc=t(2),
    )
    assert S.DETECCION_CORROBORADA not in p.current_states().values()
    assert S.REQUIERE_REVISION in p.current_states().values()
    check_invariants(r)


# --------------------------------------------------------------- pérdida / reaparición

def test_timeout_marks_lost_and_reappearance_reopens_same_track():
    p = OperationalPipeline()
    r1 = p.process_batch([obs("e1", at=0)], now_utc=t(1))
    tid = only_track(r1).track_id
    r2 = p.process_batch([], now_utc=t(20))
    assert r2.decisions == [] and p.current_states()[tid] == S.DETECCION_POSIBLE
    r3 = p.process_batch([], now_utc=t(31))
    assert only_track(r3).is_lost
    assert [(d.rule_id, d.state) for d in r3.decisions] == [("R-PERD-01", S.SEGUIMIENTO_PERDIDO)]
    # Un track que nunca alertó (solo POSIBLE) no genera alerta al perderse.
    assert r3.alerts == []
    assert any(a.action == "alerta_suprimida" for a in r3.audit_events)
    r4 = p.process_batch([obs("e2", at=60)], now_utc=t(61))
    tr = only_track(r4)
    assert tr.track_id == tid and not tr.is_lost
    assert [(d.previous_state, d.rule_id, d.state) for d in r4.decisions] == [
        (S.SEGUIMIENTO_PERDIDO, "R-REAP-01", S.DETECCION_POSIBLE)]
    assert r4.decisions[0].evidence_event_ids == ["e2"]
    for r in (r1, r2, r3, r4):
        check_invariants(r)


def test_reappearance_requires_fresh_corroboration():
    p = OperationalPipeline()
    p.process_batch(
        [obs("rid-1", at=0), obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", at=0,
                                 object_id=None)],
        now_utc=t(1),
    )
    assert list(p.current_states().values()) == [S.DETECCION_CORROBORADA]
    p.process_batch([], now_utc=t(40))
    assert list(p.current_states().values()) == [S.SEGUIMIENTO_PERDIDO]
    p.process_batch([obs("rid-2", at=50)], now_utc=t(51))
    assert list(p.current_states().values()) == [S.DETECCION_POSIBLE]
    p.process_batch([], now_utc=t(52))
    # Sin nueva evidencia independiente posterior a la reaparición, no se corrobora.
    assert list(p.current_states().values()) == [S.DETECCION_POSIBLE]


def test_late_old_observation_does_not_reopen_lost_track():
    p = OperationalPipeline()
    p.process_batch([obs("e1", at=0)], now_utc=t(1))
    p.process_batch([], now_utc=t(40))
    r = p.process_batch([obs("e0", at=5)], now_utc=t(45))  # llegó tarde, 40 s de antigüedad
    assert only_track(r).is_lost
    assert list(p.current_states().values()) == [S.SEGUIMIENTO_PERDIDO]


# ----------------------------------------------------------------- duplicados

def test_duplicates_by_event_id_and_equivalent_content_are_dropped():
    p = OperationalPipeline()
    r1 = p.process_batch([obs("e1", at=0), obs("e1", at=0)], now_utc=t(1))
    assert r1.duplicates_dropped == ["e1"] and len(r1.accepted) == 1
    r2 = p.process_batch([obs("e1", at=0), obs("e1-bis", at=0)], now_utc=t(2))
    assert r2.duplicates_dropped == ["e1", "e1-bis"] and r2.accepted == []
    assert r2.decisions == []
    actions = [a.details.get("reason_code") for a in r2.audit_events
               if a.action == "duplicado_descartado"]
    assert actions == ["DUPLICATE_EVENT_ID", "DUPLICATE_CONTENT"]
    # Misma estación y contenido pero otro instante: NO es duplicado.
    r3 = p.process_batch([obs("e2", at=1)], now_utc=t(2))
    assert r3.duplicates_dropped == [] and len(r3.accepted) == 1


# --------------------------------------------------------------------- audio

def test_acoustic_only_object_has_no_points():
    p = OperationalPipeline()
    batch = [obs(f"ac-{i}", sensor=ST.ACOUSTIC, at=i, object_id=None, pos=None, score=0.8)
             for i in range(5)]
    r = p.process_batch(batch, now_utc=t(5))
    tr = only_track(r)
    assert tr.points == []
    assert tr.sensor_types == [ST.ACOUSTIC]
    assert p.current_states()[tr.track_id] == S.DETECCION_POSIBLE
    check_invariants(r)


def test_acoustic_without_object_id_is_not_spatially_associated():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rid-1", at=0),
         obs("ac-1", sensor=ST.ACOUSTIC, at=0, object_id=None, pos=None, score=0.9)],
        now_utc=t(1),
    )
    assert len(r.tracks) == 2  # ante la duda, no asociar
    assert S.DETECCION_CORROBORADA not in p.current_states().values()
    ac_track = next(tr for tr in r.tracks if tr.sensor_types == [ST.ACOUSTIC])
    assert ac_track.points == []


def test_acoustic_with_same_object_id_corroborates_but_never_adds_position():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rid-1", at=0),
         obs("ac-1", sensor=ST.ACOUSTIC, station="EST-SIM-03", at=1, pos=None, score=0.9)],
        now_utc=t(2),
    )
    tr = only_track(r)
    assert p.current_states()[tr.track_id] == S.DETECCION_CORROBORADA
    assert all("ac-1" not in pt.source_event_ids for pt in tr.points)
    assert len(tr.points) == 1


def test_low_classifier_score_alone_is_discarded_then_recovers():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("op-1", sensor=ST.OPTICAL, object_id=None, score=0.1)], now_utc=t(1)
    )
    tr = only_track(r)
    assert [(d.rule_id, d.state) for d in r.decisions] == [("R-DESC-01", S.DESCARTADA)]
    assert not r.decisions[0].requires_human_review
    r2 = p.process_batch(
        [obs("op-2", sensor=ST.OPTICAL, object_id=None, at=1, score=0.9)], now_utc=t(2)
    )
    assert p.current_states()[tr.track_id] == S.DETECCION_POSIBLE
    check_invariants(r)
    check_invariants(r2)


# ----------------------------------------------------------- estación / calidad

def test_offline_station_contributes_no_new_evidence():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("e1", station="EST-SIM-09")], now_utc=t(1),
        station_status={"EST-SIM-09": StationStatus.OFFLINE},
    )
    assert r.accepted == [] and r.tracks == [] and r.decisions == []
    assert [x.reason_code for x in r.rejected] == ["STATION_OFFLINE"]
    assert r.rejected[0].event_id == "e1"
    # El estado se recuerda entre lotes hasta que llegue otro.
    r2 = p.process_batch([obs("e2", station="EST-SIM-09", at=1)], now_utc=t(2))
    assert [x.reason_code for x in r2.rejected] == ["STATION_OFFLINE"]
    r3 = p.process_batch([obs("e3", station="EST-SIM-09", at=2)], now_utc=t(3),
                         station_status={"EST-SIM-09": StationStatus.ONLINE})
    assert len(r3.accepted) == 1


def test_degraded_station_reduces_quality_and_blocks_corroboration():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rid-1"),
         obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", object_id=None, quality=0.9),
         obs("rad-x", sensor=ST.RADAR, station="EST-SIM-03", object_id=None, quality=0.3,
             pos=offset(LAT0, LON0, east_m=5000))],
        now_utc=t(1),
        station_status={"EST-SIM-02": StationStatus.DEGRADED,
                        "EST-SIM-03": StationStatus.DEGRADED},
    )
    # 0.9*0.5=0.45 < 0.5 (mínimo para corroborar); 0.3*0.5=0.15 < 0.2 -> rechazada.
    assert [x.reason_code for x in r.rejected] == ["LOW_QUALITY"]
    assert list(p.current_states().values()) == [S.DETECCION_POSIBLE]
    q = [a.details["quality"] for a in r.audit_events
         if a.action == "observacion_aceptada" and a.subject == "rad-1"]
    assert q == [pytest.approx(0.45)]


def test_stale_and_future_observations_rejected():
    p = OperationalPipeline()
    r = p.process_batch([obs("old", at=0), obs("fut", at=400)], now_utc=t(300))
    assert sorted(x.reason_code for x in r.rejected) == ["FUTURE_TIMESTAMP", "STALE"]
    assert r.tracks == []


def test_incomplete_observation_still_usable():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rf-1", sensor=ST.RF, object_id=None, pos=None, uncertainty=None, quality=None)],
        now_utc=t(1),
    )
    tr = only_track(r)
    assert tr.points == [] and p.current_states()[tr.track_id] == S.DETECCION_POSIBLE


# ----------------------------------------------------------------- lotes

def test_empty_batch():
    p = OperationalPipeline()
    r = p.process_batch([], now_utc=t(0))
    assert r.accepted == r.rejected == r.duplicates_dropped == []
    assert r.tracks == r.decisions == r.alerts == []
    assert [a.action for a in r.audit_events] == ["lote_recibido", "lote_procesado"]
    assert p.current_states() == {} and p.current_tracks() == []


def test_naive_now_is_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        OperationalPipeline().process_batch([], now_utc=datetime(2026, 1, 1))


def _scenario_batches():
    near = offset(LAT0, LON0, north_m=30)
    far = offset(LAT0, LON0, north_m=4000)
    return [
        ([obs("rid-2", at=1, pos=near), obs("rid-1", at=0),
          obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", at=1, object_id=None, pos=near),
          obs("ac-1", sensor=ST.ACOUSTIC, station="EST-SIM-03", at=1, object_id=None, pos=None,
              score=0.7)], t(2)),
        ([obs("rid-1", at=0), obs("x-1", object_id="UAS-SIM-0002", at=3),
          obs("x-2", object_id="UAS-SIM-0002", at=4, pos=far)], t(5)),
        ([], t(50)),
        ([obs("rid-3", at=55)], t(56)),
    ]


def test_out_of_order_observations_give_same_result():
    a = OperationalPipeline()
    b = OperationalPipeline()
    for batch, now in _scenario_batches():
        ra = a.process_batch(batch, now)
        rb = b.process_batch(list(reversed(batch)), now)
        assert ra.model_dump_json() == rb.model_dump_json()


def test_out_of_order_points_are_sorted_in_track():
    p = OperationalPipeline()
    p.process_batch([obs("e3", at=3, pos=offset(LAT0, LON0, north_m=60))], now_utc=t(4))
    r = p.process_batch([obs("e1", at=1, pos=offset(LAT0, LON0, north_m=20))], now_utc=t(5))
    tr = only_track(r)
    assert [pt.timestamp_utc for pt in tr.points] == [t(1), t(3)]
    assert tr.first_seen_utc == t(1) and tr.last_seen_utc == t(3)


def test_determinism_two_runs_identical():
    def run():
        p = OperationalPipeline()
        return [p.process_batch(b, n).model_dump(mode="json") for b, n in _scenario_batches()]

    first, second = run(), run()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for res in first:
        for d in res["decisions"]:
            assert d["rule_id"] and d["reason"] and d["evidence_event_ids"]
        for al in res["alerts"]:
            assert al["severity"] == "informativa"


def test_all_decisions_and_alerts_meet_invariants_in_scenario():
    p = OperationalPipeline(PipelineConfig(alert_on_posible=True))
    seen_states = set()
    for batch, now in _scenario_batches():
        r = p.process_batch(batch, now)
        check_invariants(r)
        seen_states |= {d.state for d in r.decisions}
    assert {S.DETECCION_CORROBORADA, S.REQUIERE_REVISION, S.SEGUIMIENTO_PERDIDO,
            S.DETECCION_POSIBLE} <= seen_states


# ------------------------------------------------------------- simulado vs real

def test_simulated_and_real_never_mix_in_a_track():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("sim-1", simulated=True), obs("real-1", simulated=False),
         obs("real-rad", sensor=ST.RADAR, station="EST-SIM-02", object_id=None, simulated=False)],
        now_utc=t(1),
    )
    assert len(r.tracks) == 2
    for tr in r.tracks:
        tracked = p.tracker.tracks[tr.track_id].observations
        assert {o.observation.is_simulated for o in tracked} == {tr.is_simulated}
    sim_track = next(tr for tr in r.tracks if tr.is_simulated)
    real_track = next(tr for tr in r.tracks if not tr.is_simulated)
    assert p.current_states()[sim_track.track_id] == S.DETECCION_POSIBLE
    assert p.current_states()[real_track.track_id] == S.DETECCION_CORROBORADA
    assert not real_track.track_id.startswith("TRK-SIM-")
    sim_decisions = [d for d in r.decisions if d.track_id == sim_track.track_id]
    assert all(d.is_simulated for d in sim_decisions)
    assert all("[SIMULADO]" in d.reason for d in sim_decisions)


# ------------------------------------------------------------- revisión humana

def test_human_review_discard_is_traceable_and_sticky_without_new_evidence():
    p = OperationalPipeline()
    r = p.process_batch([obs("e1")], now_utc=t(1))
    tid = only_track(r).track_id
    d = p.apply_human_review(tid, S.DESCARTADA, reviewer="op1", now_utc=t(2), note="globo")
    assert d.rule_id == "R-HUM-01" and d.previous_state == S.DETECCION_POSIBLE
    assert d.evidence_event_ids == ["e1"]
    r2 = p.process_batch([], now_utc=t(3))
    assert p.current_states()[tid] == S.DESCARTADA and r2.decisions == []
    assert any(a.action == "revision_humana" and a.actor == "operador:op1"
               for a in r2.audit_events)
    with pytest.raises(ValueError):
        p.apply_human_review(tid, S.SIN_OBSERVACION, reviewer="op1", now_utc=t(4))


def test_rules_table_has_stable_ids():
    ids = [row["rule_id"] for row in rules_table()]
    assert ids == ["R-PERD-01", "R-REV-01", "R-REAP-01", "R-DESC-01", "R-CORR-01",
                   "R-POS-01", "R-HUM-01"]
