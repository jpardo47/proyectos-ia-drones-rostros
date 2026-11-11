"""Clasificador ligero drone / no_drone sobre features por ventana."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.audio.features import FeatureConfig

POSITIVE = "drone"
NEGATIVE = "no_drone"
LABELS = (NEGATIVE, POSITIVE)  # índice 1 = clase positiva
FORMAT_VERSION = 1


def _build(kind: str, seed: int) -> Pipeline:
    if kind == "logreg":
        est = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, random_state=seed)
    elif kind == "rf":
        est = RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced",
                                     n_jobs=1, random_state=seed)
    else:
        raise ValueError(f"tipo de modelo desconocido: {kind} (usa 'logreg' o 'rf')")
    return Pipeline([("scaler", StandardScaler()), ("clf", est)])


class AudioClassifier:
    """StandardScaler + (regresión logística | bosque aleatorio). Umbral y metadatos incluidos."""

    def __init__(self, kind: str = "logreg", seed: int = 42, feature_config: FeatureConfig | None = None):
        self.kind = kind
        self.seed = seed
        self.feature_config = feature_config or FeatureConfig()
        self.pipeline = _build(kind, seed)
        self.threshold = 0.5
        self.metadata: dict = {}
        self.model_version = "untrained"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "AudioClassifier":
        y = np.asarray(y, dtype=int)
        if set(np.unique(y)) != {0, 1}:
            raise ValueError("se necesitan ejemplos de ambas clases (0=no_drone, 1=drone)")
        self.pipeline.fit(np.asarray(X, dtype=np.float64), y)
        self.model_version = self._compute_version()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Probabilidad de la clase `drone` por fila (n,)."""
        X = np.asarray(X, dtype=np.float64)
        if X.shape[0] == 0:
            return np.zeros(0)
        return self.pipeline.predict_proba(X)[:, 1]

    def predict(self, X: np.ndarray, threshold: float | None = None) -> np.ndarray:
        thr = self.threshold if threshold is None else threshold
        return (self.predict_proba(X) >= thr).astype(int)

    def _compute_version(self) -> str:
        h = hashlib.sha256()
        h.update(self.kind.encode())
        h.update(self.feature_config.fingerprint().encode())
        h.update(joblib.hash(self.pipeline).encode())
        return f"p2-audio-{self.kind}-{h.hexdigest()[:12]}"

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "format_version": FORMAT_VERSION,
            "kind": self.kind,
            "seed": self.seed,
            "feature_config": self.feature_config.to_dict(),
            "pipeline": self.pipeline,
            "threshold": float(self.threshold),
            "model_version": self.model_version,
            "labels": list(LABELS),
            "metadata": self.metadata,
        }, path)
        path.with_suffix(".json").write_text(json.dumps({
            "model_version": self.model_version, "kind": self.kind, "threshold": float(self.threshold),
            "feature_config": self.feature_config.to_dict(), "labels": list(LABELS), "metadata": self.metadata,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "AudioClassifier":
        d = joblib.load(Path(path))
        if d.get("format_version") != FORMAT_VERSION:
            raise ValueError("formato de modelo incompatible")
        obj = cls(d["kind"], d["seed"], FeatureConfig.from_dict(d["feature_config"]))
        obj.pipeline = d["pipeline"]
        obj.threshold = d["threshold"]
        obj.model_version = d["model_version"]
        obj.metadata = d.get("metadata", {})
        return obj
