"""Métricas binarias (positivo = drone) por ventana y por grabación."""
from __future__ import annotations

import numpy as np


def confusion(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)
    return {
        "tp": int(((y_true == 1) & (y_pred == 1)).sum()),
        "fp": int(((y_true == 0) & (y_pred == 1)).sum()),
        "fn": int(((y_true == 1) & (y_pred == 0)).sum()),
        "tn": int(((y_true == 0) & (y_pred == 0)).sum()),
    }


def binary_metrics(y_true, y_pred) -> dict:
    c = confusion(y_true, y_pred)
    tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    n = tp + fp + fn + tn
    return {
        "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        "specificity": round(spec, 4), "accuracy": round((tp + tn) / n, 4) if n else 0.0,
        "support_pos": tp + fn, "support_neg": tn + fp,
        "confusion_matrix": {"labels": ["no_drone", "drone"], "matrix": [[tn, fp], [fn, tp]], **c},
    }


def aggregate_by_group(groups, proba, y_true=None) -> dict:
    """Probabilidad media por grabación. Devuelve {grupo: (prob_media, etiqueta)}."""
    groups = np.asarray(groups)
    proba = np.asarray(proba, dtype=float)
    out = {}
    for g in sorted(set(groups.tolist())):
        m = groups == g
        lab = int(np.asarray(y_true)[m][0]) if y_true is not None else None
        out[g] = (float(proba[m].mean()), lab)
    return out


def window_and_recording_metrics(groups, y_true, proba, threshold: float) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    proba = np.asarray(proba, dtype=float)
    win = binary_metrics(y_true, (proba >= threshold).astype(int))
    agg = aggregate_by_group(groups, proba, y_true)
    rec_true = np.array([v[1] for v in agg.values()], dtype=int)
    rec_pred = np.array([v[0] >= threshold for v in agg.values()], dtype=int)
    rec = binary_metrics(rec_true, rec_pred)
    return {"threshold": threshold, "n_windows": int(y_true.size), "n_recordings": len(agg),
            "per_window": win, "per_recording": rec}
