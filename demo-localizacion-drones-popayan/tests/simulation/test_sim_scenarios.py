"""Pruebas del simulador (DATOS SIMULADOS). Deterministas y sin red."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.contracts import Observation, RawEvent, RemoteIdWireMessage, StationCategory, StationStatus
from src.simulation.scenario import get_scenario, list_scenarios, run_scenario
from src.simulation.trajectories import enu_to_latlon, haversine_m, latlon_to_enu

SCENARIOS = [
    "basico", "sin_remote_id", "duplicados", "contradictorio", "corroborado", "perdida_senal",
    "estacion_caida", "malformados", "sin_estacion_control", "rangos_100m_10km",
]


@pytest.fixture(scope="module")
def results():
    return {name: run_scenario(get_scenario(name, 42)) for name in SCENARIOS}


def _parse(ev: RawEvent):
    """Devuelve el modelo del contrato o lanza ValidationError."""
    if ev.kind == "remote_id":
        return RemoteIdWireMessage.model_validate(ev.payload)
    return Observation.model_validate(ev.payload)


def _semantic_problems(ev: RawEvent, now_end: datetime) -> list[str]:
    """Reglas minimas que el modelo permisivo de Remote ID no cubre (las aplica src/remote_id)."""
    p = ev.payload
    probs = []
    ts = p.get("timestamp_utc")
    if isinstance(ts, str):
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is None:
            probs.append("sin_zona")
        elif d > now_end + timedelta(minutes=5):
            probs.append("futuro")
    drone = p.get("drone")
    if isinstance(drone, dict) and isinstance(drone.get("latitude"), (int, float)) and abs(drone["latitude"]) > 90:
        probs.append("lat_fuera_de_rango")
    return probs


def _invalid(ev: RawEvent, end: datetime) -> bool:
    try:
        _parse(ev)
    except ValidationError:
        return True
    return bool(_semantic_problems(ev, end))


def test_lista_de_escenarios():
    assert set(list_scenarios()) == set(SCENARIOS)
    with pytest.raises(ValueError):
        get_scenario("no_existe")


def test_determinismo_misma_semilla():
    a = run_scenario(get_scenario("basico", 7)).model_dump(mode="json")
    b = run_scenario(get_scenario("basico", 7)).model_dump(mode="json")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_semillas_distintas_difieren():
    a = run_scenario(get_scenario("basico", 1))
    b = run_scenario(get_scenario("basico", 2))
    assert [e.payload for e in a.raw_events] != [e.payload for e in b.raw_events]


def test_start_utc_fijo_por_defecto():
    assert get_scenario("basico").start_utc == get_scenario("duplicados").start_utc
    assert get_scenario("basico").start_utc.tzinfo is not None


def test_truth_separado_de_raw_events(results):
    for name, r in results.items():
        assert r.is_simulated is True
        assert r.truth, name
        keys = set()
        for ev in r.raw_events:
            keys |= set(ev.payload)
        # el estado verdadero no se cuela en los payloads
        assert not keys & {"drone_id", "emits_remote_id", "emits_sound", "altitude_agl_m"}, name
        for ev in r.raw_events:
            assert "DRN-" not in json.dumps(ev.payload), name


def test_raw_events_ordenados(results):
    for name, r in results.items():
        ts = [e.received_at_utc for e in r.raw_events]
        assert ts == sorted(ts), name


def test_acustico_sin_coordenadas(results):
    n = 0
    for name, r in results.items():
        if name == "malformados":
            continue
        for ev in r.raw_events:
            if ev.kind == "observation" and ev.payload["sensor_type"] == "acoustic":
                n += 1
                assert ev.payload["latitude"] is None and ev.payload["longitude"] is None
                assert ev.payload["altitude"] is None
                assert ev.payload["classification"] == "drone"
                assert 0.0 <= ev.payload["classifier_score"] <= 1.0
    assert n > 0


def test_rf_sin_posicion(results):
    n = 0
    for name, r in results.items():
        if name == "malformados":
            continue
        for ev in r.raw_events:
            if ev.kind == "observation" and ev.payload.get("sensor_type") == "rf":
                n += 1
                assert ev.payload["latitude"] is None
    assert n > 0


def test_inst_sim_sin_coordenadas_y_probabilidad_independiente(results):
    r = results["basico"]
    for s in r.stations:
        if s.category == StationCategory.INSTITUCIONAL_ABSTRACTA:
            assert s.latitude is None and s.longitude is None
    rid_inst01 = [e for e in r.raw_events if e.station_id == "INST-SIM-01" and e.kind == "remote_id"]
    assert rid_inst01
    # tasa ~ inst_rx_prob (0.8) sobre los pasos de Remote ID, sin importar la distancia
    cfg = get_scenario("basico", 42)
    steps_rid = (cfg.duration_s // 2) * sum(1 for d in cfg.drones if d.emits_remote_id)
    assert 0.7 * steps_rid <= len(rid_inst01) <= 0.9 * steps_rid


def test_observaciones_simuladas_marcadas(results):
    for name, r in results.items():
        if name == "malformados":
            continue
        for ev in r.raw_events:
            if ev.kind == "observation":
                o = Observation.model_validate(ev.payload)
                assert o.is_simulated and o.data_origin.value == "simulation"
            else:
                assert RemoteIdWireMessage.model_validate(ev.payload).is_simulated is True


def test_payloads_validos_en_escenarios_limpios(results):
    for name in SCENARIOS:
        if name == "malformados":
            continue
        r = results[name]
        for ev in r.raw_events:
            _parse(ev)  # no debe lanzar
            assert not _semantic_problems(ev, r.end_utc), name


def test_malformados_se_detectan(results):
    r = results["malformados"]
    bad = [e for e in r.raw_events if _invalid(e, r.end_utc)]
    good = [e for e in r.raw_events if not _invalid(e, r.end_utc)]
    assert len(bad) == 28
    assert len(good) > 100  # trafico normal tambien presente
    contract_bad = 0
    for e in bad:
        try:
            _parse(e)
        except ValidationError:
            contract_bad += 1
    assert contract_bad >= 16  # rotos por el propio contrato, no solo por reglas semanticas


def test_basico_casos_remote_id(results):
    r = results["basico"]
    by_uas: dict[str, list[RemoteIdWireMessage]] = defaultdict(list)
    for e in r.raw_events:
        if e.kind == "remote_id":
            m = RemoteIdWireMessage.model_validate(e.payload)
            by_uas[m.uas_id].append(m)
    assert len(by_uas) == 2  # el tercer dron no emite Remote ID
    assert all(m.operator is not None and m.takeoff is not None for m in by_uas["SIM-UAS-0001"])
    assert all(m.operator is None and m.takeoff is not None for m in by_uas["SIM-UAS-0002"])
    assert not any(t.emits_remote_id for t in r.truth if t.drone_id == "DRN-003")


def test_sin_remote_id(results):
    r = results["sin_remote_id"]
    assert not [e for e in r.raw_events if e.kind == "remote_id"]
    assert [e for e in r.raw_events if e.kind == "observation"]
    assert not any(t.emits_remote_id for t in r.truth)


def test_sin_estacion_control(results):
    r = results["sin_estacion_control"]
    msgs = [RemoteIdWireMessage.model_validate(e.payload) for e in r.raw_events if e.kind == "remote_id"]
    assert msgs and all(m.operator is None and m.operator_id is None for m in msgs)
    assert any(m.takeoff is not None for m in msgs)
    assert any(m.takeoff is None for m in msgs)


def test_duplicados(results):
    r = results["duplicados"]
    ids = defaultdict(list)
    for e in r.raw_events:
        ids[e.payload.get("message_id") or e.payload.get("event_id")].append(e.station_id)
    repeated = {k: v for k, v in ids.items() if len(v) > 1}
    assert len(repeated) > 30
    assert any(len(set(v)) > 1 for v in repeated.values())        # varias estaciones, mismo message_id
    assert any(len(v) != len(set(v)) for v in repeated.values())  # reentrega en la misma estacion


def test_contradictorio(results):
    r = results["contradictorio"]
    by_t = defaultdict(list)
    for e in r.raw_events:
        if e.kind == "remote_id":
            m = RemoteIdWireMessage.model_validate(e.payload)
            by_t[(m.uas_id, m.timestamp_utc)].append((m.drone.latitude, m.drone.longitude))
    far = 0
    for reps in by_t.values():
        for i in range(len(reps)):
            for j in range(i + 1, len(reps)):
                if haversine_m(*reps[i], *reps[j]) > 2000:
                    far += 1
    assert far > 10
    objs = {e.payload.get("object_id") for e in r.raw_events if e.kind == "observation"}
    assert "SIM-UAS-0001" in objs  # optico/radar etiquetan el mismo object_id


def test_corroborado(results):
    r = results["corroborado"]
    truth = {t.timestamp_utc: t for t in r.truth}
    pairs = set()
    for e in r.raw_events:
        if e.kind == "remote_id":
            m = RemoteIdWireMessage.model_validate(e.payload)
            lat, lon, kind, ts = m.drone.latitude, m.drone.longitude, "remote_id", m.timestamp_utc
        else:
            o = Observation.model_validate(e.payload)
            if not o.has_position:
                continue
            lat, lon, kind, ts = o.latitude, o.longitude, o.sensor_type.value, o.timestamp_utc
        t = truth[ts]
        assert haversine_m(lat, lon, t.latitude, t.longitude) < 300.0
        pairs.add((kind, e.station_id))
    assert {k for k, _ in pairs} >= {"remote_id", "optical", "radar"}
    assert len({s for _, s in pairs}) >= 3  # fuentes independientes (estaciones distintas)


def test_perdida_senal(results):
    r = results["perdida_senal"]
    t_loss = r.start_utc + timedelta(seconds=150)
    d1 = [t for t in r.truth if t.drone_id == "DRN-001"]
    assert all(t.emits_remote_id for t in d1 if t.timestamp_utc < t_loss)
    assert not any(t.emits_remote_id or t.emits_sound for t in d1 if t.timestamp_utc >= t_loss)
    seen = {"SIM-UAS-0001": [], "SIM-UAS-0002": []}
    for e in r.raw_events:
        if e.kind == "remote_id":
            seen[e.payload["uas_id"]].append(RemoteIdWireMessage.model_validate(e.payload).timestamp_utc)
    assert seen["SIM-UAS-0001"] and max(seen["SIM-UAS-0001"]) < t_loss
    assert max(seen["SIM-UAS-0002"]) > t_loss + timedelta(seconds=100)


def test_estacion_caida(results):
    r = results["estacion_caida"]
    st = {s.station_id: s for s in r.stations}
    fall = r.start_utc + timedelta(seconds=150)
    assert st["CIV-02"].status == StationStatus.OFFLINE and st["CIV-02"].status_timestamp_utc == fall
    assert "150" in (st["CIV-02"].notes or "")
    ev02 = [e for e in r.raw_events if e.station_id == "CIV-02"]
    assert ev02 and all(e.received_at_utc < fall for e in ev02)
    assert any(e.received_at_utc > fall for e in r.raw_events if e.station_id != "CIV-02")


def test_rangos_100m_10km(results):
    r = results["rangos_100m_10km"]
    civ02 = next(s for s in r.stations if s.station_id == "CIV-02")
    expected = {"DRN-100M": 100, "DRN-500M": 500, "DRN-1KM": 1000, "DRN-3KM": 3000, "DRN-5KM": 5000, "DRN-10KM": 10000}
    first = {}
    for t in r.truth:
        first.setdefault(t.drone_id, t)
    assert set(first) == set(expected)
    for d, exp in expected.items():
        dist = haversine_m(civ02.latitude, civ02.longitude, first[d].latitude, first[d].longitude)
        assert abs(dist - exp) / exp < 0.005, (d, dist)
    # el software recibe reportes de CIV-02 para cada distancia (prueba de software, no de hardware)
    seen = defaultdict(int)
    uas_to_d = {f"SIM-UAS-{i:04d}": n for i, n in enumerate(expected, start=1)}
    for e in r.raw_events:
        if e.kind == "remote_id" and e.station_id == "CIV-02":
            seen[uas_to_d[e.payload["uas_id"]]] += 1
    assert all(seen[d] > 0 for d in expected), dict(seen)


def test_ids_deterministas(results):
    r = results["basico"]
    ids = [e.payload.get("message_id") or e.payload.get("event_id") for e in r.raw_events]
    assert all(isinstance(i, str) and i.startswith(("rid-42-", "obs-42-")) for i in ids)


def test_latlon_enu_roundtrip():
    e, n = latlon_to_enu(*enu_to_latlon(1234.0, -987.0))
    assert abs(e - 1234.0) < 1e-6 and abs(n + 987.0) < 1e-6
