"""Regresión: fragmentación de tracks detectada en integración (escenario ``basico``).

Antes de la corrección, 3 drones producían 294 tracks (270 de radar de un solo punto):
las observaciones anónimas con posición caían en "asociación ambigua", que creaba un
track nuevo, el cual aumentaba la ambigüedad del siguiente paso (cascada). Además la
puerta solo miraba puntos dentro de ``correlation_window_s`` (10 s), y las ráfagas
acústicas separadas más de 10 s abrían tracks nuevos.
"""
from __future__ import annotations

import math
from datetime import timedelta

from src.contracts import DetectionState as S
from src.contracts import IngestionResult
from src.contracts import SensorType as ST
from src.decision_agents.pipeline import OperationalPipeline, PipelineConfig
from src.tracking.geo import haversine_m
from tests.decision_agents.o3_factories import LAT0, LON0, obs, offset, t


def _noise(i: int, scale: float) -> float:
    """Ruido determinista acotado (sin aleatoriedad)."""
    return scale * math.sin(i * 12.9898) * 0.8


def _radar_track(prefix, start, velocity_e, velocity_n, n, step=2.0, sigma=30.0,
                 skip=(), station="INST-SIM-02"):
    out = []
    for i in range(n):
        if i in skip:
            continue
        ts = i * step
        pos = offset(start[0], start[1], north_m=velocity_n * ts + _noise(i, sigma),
                     east_m=velocity_e * ts + _noise(i + 7, sigma))
        out.append(obs(f"{prefix}-{i:03d}", sensor=ST.RADAR, station=station, at=ts,
                       object_id=None, pos=pos, uncertainty=sigma, quality=0.9))
    return out


def _run_in_batches(p, observations, batch_s=5.0, end_s=None):
    results = []
    last = max(o.timestamp_utc for o in observations)
    end = end_s if end_s is not None else (last - t(0)).total_seconds() + batch_s
    k = 0
    while k * batch_s < end:
        lo, hi = t(k * batch_s), t((k + 1) * batch_s)
        batch = [o for o in observations if lo <= o.timestamp_utc < hi]
        results.append(p.process_batch(batch, now_utc=hi))
        k += 1
    return results


# (a) --------------------------------------------------------------------------
def test_a_sixty_anonymous_radar_detections_form_one_track():
    # 60 detecciones (cada 2 s, 12 m/s), con 3 detecciones fallidas seguidas (hueco de 8 s)
    # y otras 4 seguidas (hueco de 10 s): no debe fragmentarse.
    detections = _radar_track("rad", (LAT0, LON0), 12.0, 5.0, 67, skip={20, 21, 22, 40, 41, 42, 43})
    assert len(detections) == 60
    p = OperationalPipeline()
    _run_in_batches(p, detections)
    tracks = p.current_tracks()
    assert len(tracks) == 1
    assert len(tracks[0].points) == 60
    assert [pt.timestamp_utc for pt in tracks[0].points] == sorted(
        pt.timestamp_utc for pt in tracks[0].points)


# (b) --------------------------------------------------------------------------
def test_b_two_well_separated_anonymous_objects_form_two_tracks():
    a = _radar_track("A", (LAT0, LON0), 10.0, 0.0, 40)
    far = offset(LAT0, LON0, north_m=2000)
    b = _radar_track("B", far, -10.0, 0.0, 40)
    p = OperationalPipeline()
    _run_in_batches(p, a + b)
    tracks = p.current_tracks()
    assert len(tracks) == 2
    for tr in tracks:
        ids = {e for pt in tr.points for e in pt.source_event_ids}
        assert len({i.split("-")[0] for i in ids}) == 1  # nunca mezcla A y B
        assert len(tr.points) == 40


# (c) --------------------------------------------------------------------------
def _crossing():
    # A va hacia el este por y=0 y B hacia el norte por x=0; ambos pasan por el origen en
    # t=30 s. Sin ruido, misma estación de radar, 10 m/s, cada 2 s.
    out = []
    for i in range(31):
        ts = 2.0 * i
        out.append(obs(f"A-{i:02d}", sensor=ST.RADAR, at=ts, object_id=None,
                       pos=offset(LAT0, LON0, east_m=-300 + 10 * ts), uncertainty=10.0))
        out.append(obs(f"B-{i:02d}", sensor=ST.RADAR, at=ts, object_id=None,
                       pos=offset(LAT0, LON0, north_m=-300 + 10 * ts), uncertainty=10.0))
    return out


def test_c_crossing_objects_no_arbitrary_association():
    p = OperationalPipeline()
    results = _run_in_batches(p, _crossing())
    # Ningún track mezcla detecciones de A y de B.
    for tr in p.current_tracks():
        owners = {e.split("-")[0] for pt in tr.points for e in pt.source_event_ids}
        assert len(owners) == 1, (tr.track_id, owners)
    # En el cruce (equidistancia) las observaciones quedan sin asociar, auditadas.
    unassoc = [a for r in results for a in r.audit_events if a.action == "observacion_no_asociada"]
    # B-15 es contenido equivalente a A-15 (misma estación, instante y posición): duplicado.
    assert "B-15" in [e for r in results for e in r.duplicates_dropped]
    assert {"A-15", "A-16", "B-16"} <= {a.subject for a in unassoc}
    assert all("ambigua" in a.details["motivo"] for a in unassoc)
    # Antes del cruce hay exactamente 2 tracks; lo que ocurre después es determinista.
    p2 = OperationalPipeline()
    results2 = _run_in_batches(p2, _crossing())
    assert [r.model_dump_json() for r in results] == [r.model_dump_json() for r in results2]


def test_c_crossing_track_count_documented():
    """Comportamiento documentado: tras un cruce sin velocidad estimada, las observaciones
    siguen siendo ambiguas mientras ambos tracks estén dentro de la puerta; al vencer
    ``association_max_gap_s`` sin asociaciones se abren tracks nuevos (sin mezclar)."""
    p = OperationalPipeline()
    _run_in_batches(p, _crossing())
    n = len(p.current_tracks())
    assert 2 <= n <= 4


# (d) --------------------------------------------------------------------------
def test_d_acoustic_bursts_same_station_one_presence_track():
    times = [0, 2, 4, 6, 20, 22, 24, 40, 42, 44, 46, 90, 92, 94]  # huecos de 14, 16 y 44 s
    batch = [obs(f"ac-{i:02d}", sensor=ST.ACOUSTIC, station="CIV-01", at=s, object_id=None,
                 pos=None, score=0.8) for i, s in enumerate(times)]
    # Dos fuentes oídas en el mismo instante también van a la misma presencia.
    batch.append(obs("ac-dup-t2", sensor=ST.ACOUSTIC, station="CIV-01", at=2, object_id=None,
                     pos=None, score=0.6))
    p = OperationalPipeline()
    results = _run_in_batches(p, batch, end_s=100)
    tracks = p.current_tracks()
    assert len(tracks) == 1
    tr = tracks[0]
    assert tr.points == [] and tr.sensor_types == [ST.ACOUSTIC] and tr.station_ids == ["CIV-01"]
    # El hueco de 44 s caduca y la presencia se reabre en el mismo track.
    rules = [d.rule_id for r in results for d in r.decisions]
    assert rules == ["R-POS-01", "R-PERD-01", "R-REAP-01"]
    assert all(r.alerts == [] for r in results)  # presencia sola: sin alertas por defecto


def test_d_presence_track_never_merges_with_positional_tracks():
    p = OperationalPipeline()
    p.process_batch(
        [obs("rad-1", sensor=ST.RADAR, station="CIV-01", object_id=None),
         obs("ac-1", sensor=ST.ACOUSTIC, station="CIV-01", object_id=None, pos=None, score=0.9)],
        now_utc=t(1),
    )
    assert len(p.current_tracks()) == 2
    assert S.DETECCION_CORROBORADA not in p.current_states().values()


# alertas proporcionales ---------------------------------------------------------
def test_alerts_not_repeated_for_same_state_of_same_track():
    p = OperationalPipeline()
    alerts = []
    # Corroborada, perdida, reaparece y vuelve a corroborarse en menos de alert_cooldown_s.
    for batch, now in [
        ([obs("rid-1", at=0), obs("rad-1", sensor=ST.RADAR, station="E2", at=0, object_id=None)], 1),
        ([], 40),
        ([obs("rid-2", at=50)], 51),
        ([obs("rad-2", sensor=ST.RADAR, station="E2", at=52, object_id=None)], 53),
    ]:
        r = p.process_batch(batch, now_utc=t(now))
        alerts += [(a.state, a.created_at_utc) for a in r.alerts]
    states = [s for s, _ in alerts]
    assert states == [S.DETECCION_CORROBORADA, S.SEGUIMIENTO_PERDIDO]
    assert list(p.current_states().values()) == [S.DETECCION_CORROBORADA]
    p2 = OperationalPipeline(PipelineConfig(alert_cooldown_s=0))
    n = 0
    for batch, now in [
        ([obs("rid-1", at=0), obs("rad-1", sensor=ST.RADAR, station="E2", at=0, object_id=None)], 1),
        ([], 40), ([obs("rid-2", at=50)], 51),
        ([obs("rad-2", sensor=ST.RADAR, station="E2", at=52, object_id=None)], 53),
    ]:
        n += len(p2.process_batch(batch, now_utc=t(now)).alerts)
    assert n == 3


def test_lost_timeout_field_name_exposed():
    names = [f for f in PipelineConfig.model_fields if "lost" in f and "timeout" in f]
    assert names == ["lost_timeout_s"]
    assert PipelineConfig().lost_timeout_s == 30.0


# (e) --------------------------------------------------------------------------
def test_e_integration_basico_three_drones_reasonable_track_count():
    from src.ingestion.agent_ingestion import IngestionAgent
    from src.ingestion.agent_validator import ValidatorAgent
    from src.simulation.scenario import get_scenario, run_scenario

    res = run_scenario(get_scenario("basico", 42))
    ing = IngestionAgent()
    val = ValidatorAgent(known_station_ids={s.station_id for s in res.stations})
    observations = []
    for ev in res.raw_events:
        r = ing.ingest(ev)
        if isinstance(r, IngestionResult):
            v = val.validate(r, ev.received_at_utc)
            if isinstance(v, IngestionResult):
                observations.append(v.observation)
    assert len(observations) > 2000

    p = OperationalPipeline()
    step = timedelta(seconds=5)
    now = res.start_utc
    n_alerts = n_decisions = 0
    while now <= res.end_utc:
        nxt = now + step
        batch = [o for o in observations if now <= o.timestamp_utc < nxt]
        out = p.process_batch(batch, now_utc=nxt)
        n_alerts += len(out.alerts)
        n_decisions += len(out.decisions)
        now = nxt

    tracks = p.current_tracks()
    positional = [tr for tr in tracks if tr.points]
    presence = [tr for tr in tracks if not tr.points]
    with_id = [tr for tr in tracks if tr.object_id]
    # Valor obtenido (seed 42): 11 tracks = 2 con Remote ID + 1 radar/óptico del dron sin
    # Remote ID + 3 de radar con 1-2 puntos (detecciones fuera de la puerta 3-sigma) +
    # 5 de presencia (acústica CIV-01/02/03/05 y RF CIV-04). Antes: 294.
    assert len(tracks) <= 15, len(tracks)
    assert len(with_id) == 2
    assert len(presence) <= 6
    big = [tr for tr in positional if len(tr.points) >= 100]
    assert len(big) == 3  # un track largo por dron
    assert sum(1 for tr in big if tr.object_id is None) == 1
    assert n_alerts <= 15 and n_decisions <= 40
    # Los tracks largos siguen al dron: puntos consecutivos plausibles (< 300 m).
    for tr in big:
        for a, b in zip(tr.points, tr.points[1:]):
            assert haversine_m(a.latitude, a.longitude, b.latitude, b.longitude) < 300
