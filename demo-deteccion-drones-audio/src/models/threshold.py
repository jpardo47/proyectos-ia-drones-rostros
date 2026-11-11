"""Calibración del umbral de decisión en el conjunto de validación."""
from __future__ import annotations

import numpy as np

from .metrics import binary_metrics


def calibrate_threshold(y_true: np.ndarray, proba: np.ndarray, criterion: str = "f1",
                        default: float = 0.5) -> tuple[float, dict]:
    """Elige el umbral que maximiza F1 (o 'youden' = recall + especificidad - 1) en validación.

    Candidatos: rejilla 0.05..0.95 (paso 0.01). Empates -> el más cercano a 0.5 (más estable).
    Si validación no tiene ambas clases, devuelve `default`.
    """
    y_true = np.asarray(y_true, dtype=int)
    proba = np.asarray(proba, dtype=float)
    if y_true.size == 0 or len(np.unique(y_true)) < 2:
        return default, {"criterion": criterion, "note": "validación sin ambas clases; umbral por defecto"}
    best_thr, best_score = default, -np.inf
    for thr in np.round(np.arange(0.05, 0.951, 0.01), 2):
        m = binary_metrics(y_true, (proba >= thr).astype(int))
        if criterion == "f1":
            score = m["f1"]
        elif criterion == "youden":
            score = m["recall"] + m["specificity"] - 1
        else:
            raise ValueError(criterion)
        if score > best_score + 1e-12 or (abs(score - best_score) <= 1e-12 and abs(thr - 0.5) < abs(best_thr - 0.5)):
            best_thr, best_score = float(thr), score
    return best_thr, {"criterion": criterion, "val_score": float(best_score)}
