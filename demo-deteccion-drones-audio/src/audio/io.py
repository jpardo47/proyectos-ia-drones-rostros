"""Carga de audio WAV: mono, remuestreo a frecuencia fija y normalización."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

DEFAULT_SR = 16_000


def to_mono(x: np.ndarray) -> np.ndarray:
    """Promedia canales: (n,) o (n, c) -> (n,)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        return x
    if x.ndim == 2:
        return x.mean(axis=1)
    raise ValueError(f"forma de audio no soportada: {x.shape}")


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Remuestreo polifásico determinista (scipy.signal.resample_poly)."""
    if sr_in == sr_out:
        return np.asarray(x, dtype=np.float64)
    frac = Fraction(sr_out, sr_in).limit_denominator(1000)
    return resample_poly(np.asarray(x, dtype=np.float64), frac.numerator, frac.denominator)


def normalize(x: np.ndarray, mode: str = "peak", eps: float = 1e-9) -> np.ndarray:
    """Normaliza amplitud. 'peak' -> max|x|=1; 'rms' -> RMS=0.1; 'none' -> sin cambio.

    Se elimina la componente continua (DC) en todos los modos salvo 'none'.
    """
    x = np.asarray(x, dtype=np.float64)
    if mode == "none" or x.size == 0:
        return x
    x = x - x.mean()
    if mode == "peak":
        peak = np.max(np.abs(x))
        return x / peak if peak > eps else x
    if mode == "rms":
        rms = np.sqrt(np.mean(x**2))
        return 0.1 * x / rms if rms > eps else x
    raise ValueError(f"modo de normalización desconocido: {mode}")


def load_wav(path: str | Path, target_sr: int = DEFAULT_SR, norm: str = "peak") -> tuple[np.ndarray, int]:
    """Lee un WAV (cualquier nº de canales / frecuencia) y devuelve (señal mono float64, target_sr)."""
    data, sr = sf.read(str(path), dtype="float64", always_2d=False)
    x = to_mono(data)
    x = resample(x, int(sr), target_sr)
    return normalize(x, norm), target_sr


def load_wav_bytes(raw: bytes, target_sr: int = DEFAULT_SR, norm: str = "peak") -> tuple[np.ndarray, int]:
    """Igual que load_wav pero desde bytes (p. ej. subida HTTP)."""
    import io

    data, sr = sf.read(io.BytesIO(raw), dtype="float64", always_2d=False)
    x = to_mono(data)
    x = resample(x, int(sr), target_sr)
    return normalize(x, norm), target_sr


def save_wav(path: str | Path, x: np.ndarray, sr: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(x, dtype=np.float32), sr, subtype="PCM_16")
