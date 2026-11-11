import numpy as np
import pytest

from src.models.classifier import AudioClassifier
from src.models.metrics import binary_metrics, window_and_recording_metrics
from src.models.splits import assert_no_leakage, mask_for, split_groups
from src.models.threshold import calibrate_threshold
from src.pipeline import predict_wav


def test_split_by_recording_no_leakage():
    groups = [f"rec{i:02d}" for i in range(20) for _ in range(5)]  # 5 ventanas por grabación
    labels = {f"rec{i:02d}": int(i < 8) for i in range(20)}
    s = split_groups(groups, labels, 0.15, 0.2, seed=42)
    assert_no_leakage(s)
    assert sorted(s["train"] + s["val"] + s["test"]) == sorted(set(groups))
    for k in ("val", "test"):  # ambas clases presentes
        assert {labels[g] for g in s[k]} == {0, 1}
    # ninguna ventana de una grabación de test está en train
    g = np.array(groups)
    assert not (mask_for(g, s["train"]) & mask_for(g, s["test"])).any()
    assert s == split_groups(groups, labels, 0.15, 0.2, seed=42)          # semilla fija
    assert s != split_groups(groups, labels, 0.15, 0.2, seed=1)


def test_leakage_detector():
    with pytest.raises(AssertionError):
        assert_no_leakage({"train": ["a", "b"], "val": ["c"], "test": ["a"]})


def test_trained_split_is_by_recording(trained):
    s, groups = trained["split"], trained["groups"]
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        assert not set(groups[mask_for(groups, s[a])]) & set(groups[mask_for(groups, s[b])])


def test_metrics_values():
    m = binary_metrics([1, 1, 0, 0, 1], [1, 0, 0, 1, 1])
    assert m["confusion_matrix"]["matrix"] == [[1, 1], [1, 2]]
    assert m["precision"] == pytest.approx(2 / 3, abs=1e-4) and m["recall"] == pytest.approx(2 / 3, abs=1e-4)
    r = window_and_recording_metrics(["a", "a", "b", "b"], [1, 1, 0, 0], [0.9, 0.4, 0.2, 0.6], 0.5)
    assert r["n_recordings"] == 2 and r["per_recording"]["f1"] == 1.0 and r["per_window"]["f1"] == 0.5


def test_threshold_calibration():
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    thr, info = calibrate_threshold(y, p)
    assert 0.3 < thr <= 0.7 and info["val_score"] == 1.0
    assert calibrate_threshold(np.zeros(3), p[:3])[0] == 0.5


def test_classifier_rejects_single_class(cfg):
    with pytest.raises(ValueError):
        AudioClassifier().fit(np.zeros((4, 3)), np.zeros(4))


@pytest.mark.parametrize("kind", ["logreg", "rf"])
def test_fit_predict_save_load_roundtrip(trained, kind, tmp_path):
    X, y = trained["X"], trained["y"]
    m = AudioClassifier(kind, 0).fit(X, y)
    p = m.predict_proba(X)
    assert p.shape == (len(X),) and ((p >= 0) & (p <= 1)).all()
    m.threshold = 0.42
    m.save(tmp_path / "m.joblib")
    m2 = AudioClassifier.load(tmp_path / "m.joblib")
    assert np.array_equal(p, m2.predict_proba(X)) and m2.threshold == 0.42
    assert m2.model_version == m.model_version and m.model_version.startswith(f"p2-audio-{kind}-")
    assert (tmp_path / "m.json").exists()


def test_model_version_reproducible(trained):
    X, y = trained["X"], trained["y"]
    assert AudioClassifier("logreg", 1).fit(X, y).model_version == AudioClassifier("logreg", 1).fit(X, y).model_version


def test_prediction_reproducible_and_sensible(trained, drone_wav, background_wav):
    m = AudioClassifier.load(trained["path"])
    a, b = predict_wav(drone_wav, m), predict_wav(drone_wav, m)
    assert a == b
    assert a["n_windows"] == len(a["windows"]) == 5
    assert a["threshold"] == m.threshold and a["model_version"] == m.model_version
    assert a["decision"] in ("drone", "no_drone")
    # sobre audio SINTÉTICO de entrenamiento el modelo debe separar las clases (prueba de humo)
    assert a["aggregate_probability"] > predict_wav(background_wav, m)["aggregate_probability"]
