import json

import pytest
from fastapi.testclient import TestClient

from src.export.observations import (
    ObservationValidationError, build_observation, export_jsonl, observations_from_prediction, validate_observation,
)
from src.models.classifier import AudioClassifier
from src.pipeline import predict_wav

TS = "2026-11-11T12:00:00Z"


def _obs(**kw):
    base = dict(score=0.8, threshold=0.5, model_version="p2-audio-test", station_id="P2-TEST",
                timestamp_utc=TS, source="DRONE_001.wav")
    base.update(kw)
    return build_observation(**base)


def test_observation_valid_and_without_coordinates():
    o = _obs()
    assert o["sensor_type"] == "acoustic" and o["classification"] == "drone"
    assert o["latitude"] is None and o["longitude"] is None and o["altitude"] is None
    assert o["data_origin"] == "replay" and o["is_simulated"] is False
    assert o["timestamp_utc"].endswith("Z")
    assert _obs(score=0.1)["classification"] == "no_drone"
    assert _obs() == _obs()  # event_id determinista


def test_simulated_origin_inferred_from_name():
    o = _obs(source="SIMULADO_drone_000.wav")
    assert o["data_origin"] == "simulation" and o["is_simulated"] is True


def test_acoustic_with_coordinates_fails_schema():
    o = _obs()
    o.update(latitude=2.44, longitude=-76.61)
    with pytest.raises(ObservationValidationError):
        validate_observation(o)
    o2 = _obs()
    o2.update(altitude=100.0, altitude_reference="agl")
    with pytest.raises(ObservationValidationError):
        validate_observation(o2)


def test_incoherent_simulation_flag_fails():
    o = _obs()
    o["is_simulated"] = True  # replay + is_simulated=true -> inválido
    with pytest.raises(ObservationValidationError):
        validate_observation(o)


def test_rejects_naive_timestamp_and_bad_origin():
    with pytest.raises(ObservationValidationError):
        _obs(timestamp_utc="2026-11-11T12:00:00")
    with pytest.raises(ObservationValidationError):
        _obs(data_origin="sensor")


def test_export_jsonl_from_prediction(trained, drone_wav, tmp_path):
    m = AudioClassifier.load(trained["path"])
    pred = predict_wav(drone_wav, m)
    obs = observations_from_prediction(pred, station_id="P2-TEST", timestamp_utc=TS, per_window=True)
    assert len(obs) == pred["n_windows"]
    assert all(o["is_simulated"] and o["data_origin"] == "simulation" for o in obs)
    p = export_jsonl(obs, tmp_path / "obs.jsonl")
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(obs)
    for line in lines:
        validate_observation(json.loads(line))
    with pytest.raises(ObservationValidationError):
        export_jsonl([{**obs[0], "latitude": 1.0, "longitude": 1.0}], tmp_path / "bad.jsonl")


def test_api_health_and_predict(trained, drone_wav):
    from app import create_app

    client = TestClient(create_app(trained["path"]))
    h = client.get("/health").json()
    assert h["model_loaded"] and h["model_version"] == trained["model"].model_version
    with open(drone_wav, "rb") as f:
        r = client.post("/predict", files={"file": ("SIMULADO_drone_000.wav", f, "audio/wav")},
                        params={"station_id": "P2-TEST", "timestamp_utc": TS})
    assert r.status_code == 200, r.text
    body = r.json()
    validate_observation(body["observation"])
    assert body["observation"]["is_simulated"] is True
    assert body["observation"]["latitude"] is None
    assert body["prediction"]["model_version"] == trained["model"].model_version
    m = AudioClassifier.load(trained["path"])
    assert body["prediction"]["aggregate_probability"] == predict_wav(drone_wav, m)["aggregate_probability"]


def test_api_without_model_and_bad_audio(tmp_path, trained):
    from app import create_app

    c = TestClient(create_app(tmp_path / "no_existe.joblib"))
    assert c.get("/health").json()["model_loaded"] is False
    assert c.post("/predict", files={"file": ("x.wav", b"abc", "audio/wav")}).status_code == 503
    c2 = TestClient(create_app(trained["path"]))
    assert c2.post("/predict", files={"file": ("x.wav", b"no es audio", "audio/wav")}).status_code == 400
