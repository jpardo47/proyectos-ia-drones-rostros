"""Segmentación en ventanas de duración fija con solape."""
from __future__ import annotations

import numpy as np


def frame_signal(x: np.ndarray, sr: int, window_s: float = 1.0, hop_s: float = 0.5,
                 pad_last: bool = True) -> np.ndarray:
    """Divide la señal en ventanas (n_windows, window_len).

    - Ventanas de `window_s` segundos separadas `hop_s` segundos (solape = window_s - hop_s).
    - Si la señal es más corta que una ventana y `pad_last`, se rellena con ceros (1 ventana).
    - Una cola final se incluye (rellenada con ceros) solo si cubre al menos media ventana.
    """
    x = np.asarray(x, dtype=np.float64)
    win = int(round(window_s * sr))
    hop = int(round(hop_s * sr))
    if win <= 0 or hop <= 0:
        raise ValueError("window_s y hop_s deben ser > 0")
    n = x.shape[0]
    if n < win:
        if not pad_last or n == 0:
            return np.zeros((0, win))
        out = np.zeros((1, win))
        out[0, :n] = x
        return out
    starts = list(range(0, n - win + 1, hop))
    last_end = starts[-1] + win
    if pad_last and n - last_end > 0:
        nxt = starts[-1] + hop
        if n - nxt >= win // 2:
            starts.append(nxt)
    frames = np.zeros((len(starts), win))
    for i, s in enumerate(starts):
        seg = x[s:s + win]
        frames[i, :seg.shape[0]] = seg
    return frames


def window_times(n_windows: int, hop_s: float, window_s: float) -> list[tuple[float, float]]:
    """(inicio, fin) en segundos de cada ventana, relativo al inicio del archivo."""
    return [(round(i * hop_s, 6), round(i * hop_s + window_s, 6)) for i in range(n_windows)]
