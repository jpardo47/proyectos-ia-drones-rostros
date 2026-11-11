import numpy as np
import pytest

from src.audio.features import FeatureConfig, extract_features, log_mel, mel_filterbank, window_features
from src.audio.io import load_wav, normalize, resample, save_wav
from src.audio.segment import frame_signal
from src.audio.synthetic import SIMULATED_PREFIX, synth_background, synth_drone


def test_load_wav_stereo_44k_to_mono_16k(tmp_path, rng):
    x = rng.standard_normal((44_100, 2)) * 0.1
    p = tmp_path / "st.wav"
    import soundfile as sf
    sf.write(p, x, 44_100)
    y, sr = load_wav(p, 16_000)
    assert sr == 16_000 and y.ndim == 1
    assert abs(len(y) - 16_000) <= 2
    assert np.isclose(np.max(np.abs(y)), 1.0)


def test_resample_identity_and_normalize_modes(rng):
    x = rng.standard_normal(1000)
    assert np.array_equal(resample(x, 16000, 16000), x)
    assert np.isclose(np.sqrt(np.mean(normalize(x, "rms") ** 2)), 0.1)
    assert np.allclose(normalize(np.zeros(10)), 0)
    with pytest.raises(ValueError):
        normalize(x, "otro")


def test_frame_signal_shapes():
    sr = 16_000
    x = np.ones(int(3.0 * sr))
    f = frame_signal(x, sr, 1.0, 0.5)
    assert f.shape == (5, sr)          # 0,0.5,1,1.5,2 s
    short = frame_signal(np.ones(4000), sr, 1.0, 0.5)
    assert short.shape == (1, sr) and short[0, 4000:].sum() == 0
    tail = frame_signal(np.ones(int(2.6 * sr)), sr, 1.0, 0.5)
    assert tail.shape[0] == 5          # ventana extra en 2.0 s con 0.6 s de audio (>= media) -> se incluye
    assert tail[4, int(0.6 * sr):].sum() == 0
    exact = frame_signal(np.ones(int(2.0 * sr)), sr, 1.0, 0.5)
    assert exact.shape[0] == 3         # sin cola: no se añade ventana


def test_mel_filterbank_shape_nonneg():
    fb = mel_filterbank(16_000, 512, 40, 50.0, 8000.0)
    assert fb.shape == (40, 257) and (fb >= 0).all() and (fb.sum(1) > 0).all()


def test_feature_shapes(cfg, rng):
    x = synth_drone(2.0, cfg.sample_rate, rng)
    lm = log_mel(x, cfg)
    assert lm.shape[1] == cfg.n_mels
    v = window_features(x[: cfg.sample_rate], cfg)
    assert v.shape == (cfg.n_features,) == (len(cfg.feature_names()),)
    X = extract_features(x, cfg)
    assert X.shape == (3, cfg.n_features) and np.isfinite(X).all()


def test_features_deterministic(cfg):
    x = synth_background(1.5, cfg.sample_rate, np.random.default_rng(3))
    assert np.array_equal(extract_features(x, cfg), extract_features(x.copy(), cfg))


def test_synthetic_is_reproducible_and_marked(tmp_path):
    from src.audio.synthetic import generate_synthetic_dataset
    a = generate_synthetic_dataset(tmp_path / "a", 2, 1.0, seed=1)
    b = generate_synthetic_dataset(tmp_path / "b", 2, 1.0, seed=1)
    assert all(r["data_origin"] == "simulation" for r in a)
    assert all(r["group"].startswith(SIMULATED_PREFIX) for r in a)
    ya, _ = load_wav(a[0]["path"]); yb, _ = load_wav(b[0]["path"])
    assert np.array_equal(ya, yb)


def test_custom_config_changes_dim():
    cfg = FeatureConfig(n_mels=32, n_mfcc=13)
    x = np.random.default_rng(0).standard_normal(16_000)
    assert extract_features(x, cfg).shape[1] == cfg.n_features == 2 * 32 + 4 * 13 + 8
