"""Features log-mel y MFCC con estadísticos por ventana (implementación con numpy/scipy).

Se implementa el banco de filtros mel (fórmula HTK) y la DCT con scipy para no depender de
librosa/numba y mantener resultados deterministas y reproducibles.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np
from scipy.fft import dct, rfft
from scipy.signal import get_window

from .segment import frame_signal


@dataclass(frozen=True)
class FeatureConfig:
    sample_rate: int = 16_000
    window_s: float = 1.0          # duración de la ventana de clasificación
    hop_s: float = 0.5             # salto entre ventanas (solape 50 %)
    n_fft: int = 512
    frame_length: int = 400        # 25 ms a 16 kHz
    frame_hop: int = 160           # 10 ms a 16 kHz
    n_mels: int = 40
    fmin: float = 50.0
    fmax: float = 8_000.0
    n_mfcc: int = 20
    norm: str = "peak"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureConfig":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def fingerprint(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @property
    def n_features(self) -> int:
        # media+std de log-mel, media+std de MFCC, media+std de delta-MFCC, 4 espectrales (media+std)
        return 2 * self.n_mels + 2 * self.n_mfcc + 2 * self.n_mfcc + 2 * 4

    def feature_names(self) -> list[str]:
        names = [f"logmel_mean_{i}" for i in range(self.n_mels)]
        names += [f"logmel_std_{i}" for i in range(self.n_mels)]
        names += [f"mfcc_mean_{i}" for i in range(self.n_mfcc)]
        names += [f"mfcc_std_{i}" for i in range(self.n_mfcc)]
        names += [f"dmfcc_mean_{i}" for i in range(self.n_mfcc)]
        names += [f"dmfcc_std_{i}" for i in range(self.n_mfcc)]
        for s in ("centroid", "bandwidth", "flatness", "rms_db"):
            names += [f"{s}_mean", f"{s}_std"]
        return names


def hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m, dtype=np.float64) / 2595.0) - 1.0)


@lru_cache(maxsize=16)
def mel_filterbank(sr: int, n_fft: int, n_mels: int, fmin: float, fmax: float) -> np.ndarray:
    """Matriz (n_mels, n_fft//2+1) de filtros triangulares mel (HTK)."""
    fmax = min(fmax, sr / 2)
    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    hz = mel_to_hz(mels)
    bins = np.fft.rfftfreq(n_fft, 1.0 / sr)
    fb = np.zeros((n_mels, bins.size))
    for i in range(n_mels):
        lo, ce, hi = hz[i], hz[i + 1], hz[i + 2]
        up = (bins - lo) / max(ce - lo, 1e-9)
        down = (hi - bins) / max(hi - ce, 1e-9)
        fb[i] = np.maximum(0.0, np.minimum(up, down))
    # normalización por área (Slaney) para que bandas anchas no dominen
    enorm = 2.0 / np.maximum(hz[2:n_mels + 2] - hz[:n_mels], 1e-9)
    fb *= enorm[:, None]
    fb.setflags(write=False)
    return fb


def power_spectrogram(x: np.ndarray, cfg: FeatureConfig) -> np.ndarray:
    """Espectrograma de potencia (n_frames, n_fft//2+1) con ventana Hann."""
    frames = frame_signal(x, cfg.sample_rate, cfg.frame_length / cfg.sample_rate,
                          cfg.frame_hop / cfg.sample_rate, pad_last=True)
    w = get_window("hann", cfg.frame_length, fftbins=True)
    spec = rfft(frames * w, n=cfg.n_fft, axis=1)
    return (np.abs(spec) ** 2) / cfg.n_fft


def log_mel(x: np.ndarray, cfg: FeatureConfig) -> np.ndarray:
    """Log-mel (n_frames, n_mels) en dB."""
    p = power_spectrogram(x, cfg)
    fb = mel_filterbank(cfg.sample_rate, cfg.n_fft, cfg.n_mels, cfg.fmin, cfg.fmax)
    mel = p @ fb.T
    return 10.0 * np.log10(np.maximum(mel, 1e-10))


def mfcc_from_logmel(lm: np.ndarray, n_mfcc: int) -> np.ndarray:
    return dct(lm, type=2, axis=1, norm="ortho")[:, :n_mfcc]


def delta(feat: np.ndarray, width: int = 2) -> np.ndarray:
    """Derivada temporal por regresión (como en HTK)."""
    n = feat.shape[0]
    if n < 2:
        return np.zeros_like(feat)
    pad = np.pad(feat, ((width, width), (0, 0)), mode="edge")
    num = sum(k * (pad[width + k:width + k + n] - pad[width - k:width - k + n]) for k in range(1, width + 1))
    return num / (2 * sum(k * k for k in range(1, width + 1)))


def spectral_stats(p: np.ndarray, sr: int, n_fft: int) -> np.ndarray:
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    tot = p.sum(axis=1) + 1e-12
    centroid = (p * freqs).sum(axis=1) / tot
    bw = np.sqrt((p * (freqs - centroid[:, None]) ** 2).sum(axis=1) / tot)
    flat = np.exp(np.mean(np.log(p + 1e-12), axis=1)) / (np.mean(p, axis=1) + 1e-12)
    rms_db = 10 * np.log10(np.mean(p, axis=1) + 1e-12)
    out = []
    for v in (centroid / (sr / 2), bw / (sr / 2), flat, rms_db):
        out += [v.mean(), v.std()]
    return np.array(out)


def window_features(win: np.ndarray, cfg: FeatureConfig) -> np.ndarray:
    """Vector de features (cfg.n_features,) para una ventana de audio."""
    p = power_spectrogram(win, cfg)
    fb = mel_filterbank(cfg.sample_rate, cfg.n_fft, cfg.n_mels, cfg.fmin, cfg.fmax)
    lm = 10.0 * np.log10(np.maximum(p @ fb.T, 1e-10))
    mf = mfcc_from_logmel(lm, cfg.n_mfcc)
    dmf = delta(mf)
    vec = np.concatenate([
        lm.mean(0), lm.std(0), mf.mean(0), mf.std(0), dmf.mean(0), dmf.std(0),
        spectral_stats(p, cfg.sample_rate, cfg.n_fft),
    ])
    return vec


def extract_features(x: np.ndarray, cfg: FeatureConfig) -> np.ndarray:
    """Señal completa -> matriz (n_windows, n_features)."""
    wins = frame_signal(x, cfg.sample_rate, cfg.window_s, cfg.hop_s, pad_last=True)
    if wins.shape[0] == 0:
        return np.zeros((0, cfg.n_features))
    return np.vstack([window_features(w, cfg) for w in wins])
