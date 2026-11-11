"""Fixtures deterministas basadas en audio SINTÉTICO (SIMULADO)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.audio.features import FeatureConfig
from src.audio.synthetic import generate_synthetic_dataset
from src.dataset import featurize_manifest
from src.models.classifier import AudioClassifier
from src.models.splits import mask_for, split_groups
from src.models.threshold import calibrate_threshold


@pytest.fixture(scope="session")
def cfg() -> FeatureConfig:
    return FeatureConfig()


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("sintetico")
    rows = generate_synthetic_dataset(d, n_per_class=8, duration_s=3.0, seed=7)
    return d, pd.DataFrame(rows)


@pytest.fixture(scope="session")
def trained(synth_dir, cfg, tmp_path_factory):
    _, df = synth_dir
    X, y, groups, _ = featurize_manifest(df, cfg)
    split = split_groups(list(groups), {g: int(l) for g, l in zip(groups, y)}, 0.2, 0.25, seed=42)
    tr, va = mask_for(groups, split["train"]), mask_for(groups, split["val"])
    model = AudioClassifier("logreg", 42, cfg).fit(X[tr], y[tr])
    model.threshold, _ = calibrate_threshold(y[va], model.predict_proba(X[va]))
    model.metadata = {"data_origin": "simulation", "is_simulated": True}
    path = tmp_path_factory.mktemp("modelo") / "SIMULADO_test.joblib"
    model.save(path)
    return {"model": model, "path": path, "X": X, "y": y, "groups": groups, "split": split}


@pytest.fixture(scope="session")
def drone_wav(synth_dir):
    d, _ = synth_dir
    return d / "SIMULADO_drone_000.wav"


@pytest.fixture(scope="session")
def background_wav(synth_dir):
    d, _ = synth_dir
    return d / "SIMULADO_no_drone_000.wav"


@pytest.fixture
def rng():
    return np.random.default_rng(0)
