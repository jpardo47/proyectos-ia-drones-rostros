"""Pipeline de extremo a extremo: WAV -> ventanas -> features -> probabilidades -> decisión."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from src.audio.features import FeatureConfig, extract_features
from src.audio.io import load_wav, load_wav_bytes
from src.audio.segment import window_times
from src.models.classifier import AudioClassifier

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "modelos" / "audio_clf.joblib"


def features_for_file(path: str | Path, cfg: FeatureConfig) -> np.ndarray:
    x, _ = load_wav(path, cfg.sample_rate, cfg.norm)
    return extract_features(x, cfg)


def predict_signal(x: np.ndarray, model: AudioClassifier, source: str | None = None) -> dict:
    cfg = model.feature_config
    X = extract_features(x, cfg)
    proba = model.predict_proba(X)
    times = window_times(len(proba), cfg.hop_s, cfg.window_s)
    agg = float(proba.mean()) if proba.size else 0.0
    return {
        "source": source,
        "duration_s": round(x.shape[0] / cfg.sample_rate, 4),
        "sample_rate": cfg.sample_rate,
        "n_windows": int(proba.size),
        "windows": [{"index": i, "start_s": s, "end_s": e, "probability": round(float(p), 6)}
                    for i, ((s, e), p) in enumerate(zip(times, proba))],
        "aggregation": "mean_window_probability",
        "aggregate_probability": round(agg, 6),
        "threshold": float(model.threshold),
        "decision": "drone" if agg >= model.threshold else "no_drone",
        "model_version": model.model_version,
        "model_data_origin": model.metadata.get("data_origin", "unknown"),
        "note": "La clasificación de audio no estima coordenadas, altura ni distancia.",
    }


def predict_wav(path: str | Path, model: AudioClassifier) -> dict:
    x, _ = load_wav(path, model.feature_config.sample_rate, model.feature_config.norm)
    return predict_signal(x, model, source=str(path))


def predict_wav_bytes(raw: bytes, model: AudioClassifier, source: str | None = None) -> dict:
    x, _ = load_wav_bytes(raw, model.feature_config.sample_rate, model.feature_config.norm)
    return predict_signal(x, model, source=source)
