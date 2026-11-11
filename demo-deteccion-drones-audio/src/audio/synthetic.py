"""Generador de audio SINTÉTICO — SIMULADO.

Solo para pruebas de humo y tests. NO es un sustituto de datos reales ni sirve para estimar
rendimiento real. Los archivos generados llevan el prefijo `SIMULADO_` y las observaciones
derivadas deben exportarse con data_origin="simulation" e is_simulated=true.

- clase `drone`: zumbido de rotor = fundamental (90-260 Hz) + armónicos, con modulación de
  amplitud (paso de pala) y deriva lenta de frecuencia, más ruido de fondo.
- clase `no_drone`: ruido ambiente coloreado (rosa/marrón) con envolvente lenta tipo viento y
  transitorios ocasionales; sin estructura armónica sostenida.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SIMULATED_TAG = "SIMULADO"
SIMULATED_PREFIX = f"{SIMULATED_TAG}_"


def _colored_noise(n: int, rng: np.random.Generator, exponent: float) -> np.ndarray:
    """Ruido 1/f^exponent (0 blanco, 1 rosa, 2 marrón)."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n)
    f[0] = f[1] if n > 1 else 1.0
    spec = spec / (f ** (exponent / 2.0))
    out = np.fft.irfft(spec, n=n)
    return out / (np.std(out) + 1e-12)


def synth_drone(duration_s: float, sr: int, rng: np.random.Generator, snr_db: float | None = None) -> np.ndarray:
    n = int(duration_s * sr)
    t = np.arange(n) / sr
    f0 = rng.uniform(90, 260)
    drift = 1.0 + 0.03 * np.sin(2 * np.pi * rng.uniform(0.05, 0.3) * t + rng.uniform(0, 2 * np.pi))
    phase = 2 * np.pi * np.cumsum(f0 * drift) / sr
    sig = np.zeros(n)
    for h in range(1, 9):
        sig += (1.0 / h ** rng.uniform(0.6, 1.2)) * np.sin(h * phase + rng.uniform(0, 2 * np.pi))
    am = 1.0 + 0.35 * np.sin(2 * np.pi * rng.uniform(8, 25) * t)
    sig *= am
    sig /= np.std(sig) + 1e-12
    snr_db = rng.uniform(0, 15) if snr_db is None else snr_db
    noise = _colored_noise(n, rng, rng.uniform(0.5, 1.5))
    x = sig + noise * 10 ** (-snr_db / 20)
    return 0.5 * x / (np.max(np.abs(x)) + 1e-12)


def synth_background(duration_s: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(duration_s * sr)
    t = np.arange(n) / sr
    x = _colored_noise(n, rng, rng.uniform(0.8, 2.0))
    env = 1.0 + 0.6 * np.sin(2 * np.pi * rng.uniform(0.1, 0.8) * t + rng.uniform(0, 2 * np.pi))
    x *= env
    for _ in range(rng.integers(0, 4)):  # transitorios (golpes, pasos)
        s = rng.integers(0, max(1, n - sr // 10))
        L = int(sr * rng.uniform(0.01, 0.08))
        x[s:s + L] += rng.uniform(2, 5) * rng.standard_normal(min(L, n - s)) * np.exp(-np.linspace(0, 6, min(L, n - s)))
    return 0.5 * x / (np.max(np.abs(x)) + 1e-12)


def generate_synthetic_dataset(out_dir: str | Path, n_per_class: int = 12, duration_s: float = 4.0,
                               sr: int = 16_000, seed: int = 0) -> list[dict]:
    """Escribe WAV SIMULADOS y devuelve el manifiesto [{path, label, group, data_origin}]."""
    from .io import save_wav

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows = []
    for label in ("drone", "no_drone"):
        for i in range(n_per_class):
            x = synth_drone(duration_s, sr, rng) if label == "drone" else synth_background(duration_s, sr, rng)
            name = f"{SIMULATED_PREFIX}{label}_{i:03d}.wav"
            save_wav(out / name, x, sr)
            rows.append({"path": str(out / name), "label": label, "group": name, "data_origin": "simulation"})
    return rows
