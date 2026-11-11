import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from src.api import main as api_main
from src.contracts import load_default_stations
from src.storage import Storage
from tests.s2_support import (FakeIngestion, FakePipeline, FakeValidator, at, fake_simulate, make_alert,
                              make_decision, make_ingestion, make_obs, make_pipeline_result, make_track)

TOKEN = "token-de-prueba"
HDR = {"X-API-Token": TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("POPAYAN_DB_PATH", str(tmp_path / "api.sqlite"))
    monkeypatch.setenv("POPAYAN_API_TOKEN", TOKEN)
    monkeypatch.delenv("POPAYAN_DEMO_OPEN", raising=False)
    monkeypatch.setattr(api_main, "_get_pipeline", lambda: None)  # solo persistir salvo que se indique
    api_main._storages.clear()
    with TestClient(api_main.app) as c:
        yield c
    for s in api_main._storages.values():
        s.close()
    api_main._storages.clear()


@pytest.fixture()
def seeded(client):
    st = api_main.get_storage()
    st.upsert_stations(load_default_stations())
    st.save_ingestion(make_ingestion("E1", t=0))
    st.save_ingestion(make_ingestion("E2", station="CIV-02", t=10))
    st.save_rejected(__import__("tests.s2_support", fromlist=["x"]).make_rejected())
    res = make_pipeline_result()
    # track adicional de un solo punto y otro sin puntos
    res = res.model_copy(update={"tracks": [make_track(), make_track("TRK-2", n_points=1, stations=("INST-SIM-02",)),
                                            make_track("TRK-3", n_points=0)]})
    st.save_pipeline_result(res)
    return client


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["is_simulated"] is True


def test_read_endpoints(seeded):
    c = seeded
    assert len(c.get("/stations").json()) == 7
    assert len(c.get("/observations").json()) == 3  # E1, E2 y E0 (aceptada por pipeline)
    assert [o["event_id"] for o in c.get("/observations", params={"station_id": "CIV-02"}).json()] == ["E2"]
    assert len(c.get("/observations", params={"limit": 1}).json()) == 1
    assert c.get("/observations", params={"limit": 0}).status_code == 422
    assert len(c.get("/observations", params={"desde": at(5).isoformat(), "hasta": at(15).isoformat()}).json()) == 1
    tracks = c.get("/tracks").json()
    assert {t["track_id"] for t in tracks} == {"TRK-1", "TRK-2", "TRK-3"}
    t1 = next(t for t in tracks if t["track_id"] == "TRK-1")
    assert t1["state"] == "DETECCION_POSIBLE" and t1["rule_id"] == "R-TEST" and t1["reason"]
    detail = c.get("/tracks/TRK-1").json()
    assert detail["decisions"] and len(detail["points"]) == 3
    assert c.get("/tracks/NOPE").status_code == 404
    assert len(c.get("/decisions").json()) == 1
    assert len(c.get("/alerts").json()) == 1
    assert c.get("/alerts", params={"review_status": "confirmada"}).json() == []
    assert c.get("/alerts", params={"review_status": "inventado"}).status_code == 422
    assert len(c.get("/audit").json()) == 1
    assert c.get("/rejected").json()[0]["reason_code"] == "MALFORMED"


def test_review_requires_token_and_writes_audit(seeded):
    c = seeded
    body = {"status": "confirmada", "reviewer": "ana", "note": "revisada (simulada)"}
    assert c.post("/alerts/ALR-1/review", json=body).status_code == 401
    assert c.post("/alerts/ALR-1/review", json=body, headers={"X-API-Token": "otro"}).status_code == 401
    r = c.post("/alerts/ALR-1/review", json=body, headers=HDR)
    assert r.status_code == 200
    assert r.json()["review_status"] == "confirmada" and r.json()["reviewed_by"] == "ana"
    audit = c.get("/audit").json()
    assert any(e["actor"] == "operador:ana" and e["subject"] == "ALR-1" for e in audit)
    assert c.post("/alerts/NOPE/review", json=body, headers=HDR).status_code == 404
    assert c.post("/alerts/ALR-1/review", json={**body, "status": "pendiente"}, headers=HDR).status_code == 422
    assert c.post("/alerts/ALR-1/review", json={**body, "reviewer": ""}, headers=HDR).status_code == 422
    assert c.post("/alerts/ALR-1/review", json={**body, "status": "otro"}, headers=HDR).status_code == 422


def test_write_disabled_without_token_env(seeded, monkeypatch):
    monkeypatch.delenv("POPAYAN_API_TOKEN")
    body = {"status": "confirmada", "reviewer": "ana"}
    assert seeded.post("/alerts/ALR-1/review", json=body).status_code == 403
    assert seeded.post("/alerts/ALR-1/review", json=body, headers=HDR).status_code == 403
    assert seeded.post("/observations", json=make_obs().model_dump(mode="json")).status_code == 403
    assert seeded.post("/demo/run", json={}).status_code == 403
    monkeypatch.setenv("POPAYAN_DEMO_OPEN", "1")
    assert seeded.post("/alerts/ALR-1/review", json=body).status_code == 200


def test_post_observation_valid_and_invalid(client):
    good = make_obs("P1").model_dump(mode="json")
    assert client.post("/observations", json=good).status_code == 401
    r = client.post("/observations", json=good, headers=HDR)
    assert r.status_code == 201 and r.json()["persisted"] is True and r.json()["pipeline_processed"] is False
    assert [o["event_id"] for o in client.get("/observations").json()] == ["P1"]

    # acustica con coordenadas -> 422
    bad = make_obs("P2").model_dump(mode="json")
    bad["sensor_type"] = "acoustic"
    r = client.post("/observations", json=bad, headers=HDR)
    assert r.status_code == 422 and "acustica" in json.dumps(r.json(), ensure_ascii=False).lower().replace("ú", "u")
    # campo desconocido, sin zona horaria, fuera de rango
    assert client.post("/observations", json={**good, "extra": 1}, headers=HDR).status_code == 422
    assert client.post("/observations", json={**good, "timestamp_utc": "2026-01-01T00:00:00"}, headers=HDR).status_code == 422
    assert client.post("/observations", json={**good, "latitude": 123.0}, headers=HDR).status_code == 422
    assert client.post("/observations", json={**good, "is_simulated": False}, headers=HDR).status_code == 422
    assert client.post("/observations", json={}, headers=HDR).status_code == 422
    assert len(client.get("/observations").json()) == 1


def test_post_observation_goes_through_pipeline_when_available(client, monkeypatch):
    pipe = FakePipeline()
    monkeypatch.setattr(api_main, "_get_pipeline", lambda: pipe)
    r = client.post("/observations", json=make_obs("P1").model_dump(mode="json"), headers=HDR)
    assert r.status_code == 201 and r.json()["pipeline_processed"] is True
    assert len(pipe.calls) == 1
    assert client.get("/tracks").json()[0]["track_id"] == "TRK-1"
    assert len(client.get("/alerts").json()) == 1


def test_demo_run_endpoint(client, monkeypatch):
    from src.orchestration import runner

    real = runner.run_demo

    def fake_run(scenario, seed, **kw):
        return real(scenario, seed, simulate=fake_simulate, ingestion_agent=FakeIngestion(),
                    validator_agent=FakeValidator(), pipeline=FakePipeline(), **kw)

    monkeypatch.setattr(runner, "run_demo", fake_run)
    r = client.post("/demo/run", json={"scenario": "basico", "seed": 7}, headers=HDR)
    assert r.status_code == 200 and r.json()["seed"] == 7 and r.json()["is_simulated"] is True
    assert client.get("/tracks").json()[0]["is_simulated"] is True
    assert client.post("/demo/run", json={"scenario": "../x"}, headers=HDR).status_code == 422
    assert client.post("/demo/run", json={"seed": -1}, headers=HDR).status_code == 422

    def boom(*a, **k):
        raise ImportError("falta el modulo")

    monkeypatch.setattr(runner, "run_demo", boom)
    assert client.post("/demo/run", json={}, headers=HDR).status_code == 503


def test_export_observations_csv(seeded):
    r = seeded.get("/export/observations.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 3
    assert rows[0]["is_simulated"] == "True" and rows[0]["aviso"] == "DATOS SIMULADOS"
    assert {"event_id", "station_id", "sensor_type", "timestamp_utc", "raw_reference"} <= set(rows[0])


def test_csv_neutralizes_formulas(client):
    st = api_main.get_storage()
    st.save_ingestion(make_ingestion("F1", with_related=False, raw_reference="=HYPERLINK(\"x\")"))
    rows = list(csv.DictReader(io.StringIO(client.get("/export/observations.csv").text)))
    assert rows[0]["raw_reference"].startswith("'=")


def test_export_tracks_geojson(seeded):
    r = seeded.get("/export/tracks.geojson")
    assert r.status_code == 200
    gj = r.json()
    assert gj["type"] == "FeatureCollection" and gj["disclaimer"] == "DATOS SIMULADOS"
    feats = {f["properties"]["track_id"]: f for f in gj["features"]}
    assert set(feats) == {"TRK-1", "TRK-2"}  # TRK-3 no tiene puntos
    assert feats["TRK-1"]["geometry"]["type"] == "LineString" and len(feats["TRK-1"]["geometry"]["coordinates"]) == 3
    assert feats["TRK-2"]["geometry"]["type"] == "Point"
    for f in feats.values():
        p = f["properties"]
        assert p["is_simulated"] is True and p["disclaimer"] == "DATOS SIMULADOS"
        lon, lat = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"]
        assert -180 <= lon <= 180 and -90 <= lat <= 90
    assert feats["TRK-1"]["properties"]["state"] == "DETECCION_POSIBLE"


def test_export_stations_geojson_excludes_inst_sim(seeded):
    gj = seeded.get("/export/stations.geojson").json()
    ids = [f["properties"]["station_id"] for f in gj["features"]]
    assert ids == ["CIV-01", "CIV-02", "CIV-03", "CIV-04", "CIV-05"]
    assert all(f["properties"]["is_fictitious"] is True for f in gj["features"])
    assert "INST-SIM" not in json.dumps(gj["features"])
    # y la lista de estaciones si los incluye, pero sin coordenadas
    inst = [s for s in seeded.get("/stations").json() if s["station_id"].startswith("INST-SIM")]
    assert len(inst) == 2 and all(s["latitude"] is None for s in inst)


def test_track_geojson_never_has_geometry_for_inst_sim(seeded):
    gj = seeded.get("/export/tracks.geojson").json()
    for f in gj["features"]:
        assert "INST-SIM" not in json.dumps(f["geometry"])
