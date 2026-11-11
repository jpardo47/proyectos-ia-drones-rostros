"""División train/val/test POR GRABACIÓN ORIGINAL (grupo), nunca por ventana.

Se reparte cada clase por separado (estratificación a nivel de grabación) con un generador
de semilla fija. Todas las ventanas de una grabación caen en la misma partición.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def split_groups(groups: list[str], group_labels: dict[str, int], val_frac: float = 0.15,
                 test_frac: float = 0.2, seed: int = 42) -> dict[str, list[str]]:
    """Devuelve {'train': [...], 'val': [...], 'test': [...]} con identificadores de grabación.

    `groups`: lista de grabaciones (únicas o no); `group_labels`: grabación -> etiqueta (0/1).
    Garantiza al menos 1 grabación por clase en val y test cuando la clase tiene >= 3 grabaciones.
    """
    uniq = sorted(set(groups))
    by_class: dict[int, list[str]] = defaultdict(list)
    for g in uniq:
        by_class[int(group_labels[g])].append(g)
    rng = np.random.default_rng(seed)
    out = {"train": [], "val": [], "test": []}
    for label in sorted(by_class):
        gs = list(by_class[label])
        rng.shuffle(gs)
        n = len(gs)
        n_test = int(round(n * test_frac))
        n_val = int(round(n * val_frac))
        if n >= 3:
            n_test = max(1, n_test)
            n_val = max(1, n_val)
        if n_test + n_val >= n:
            n_val = max(0, min(n_val, n - n_test - 1))
        out["test"] += gs[:n_test]
        out["val"] += gs[n_test:n_test + n_val]
        out["train"] += gs[n_test + n_val:]
    for k in out:
        out[k] = sorted(out[k])
    assert_no_leakage(out)
    return out


def assert_no_leakage(split: dict[str, list[str]]) -> None:
    a, b, c = (set(split[k]) for k in ("train", "val", "test"))
    if a & b or a & c or b & c:
        raise AssertionError("fuga: una grabación aparece en más de una partición")


def mask_for(groups_per_window: np.ndarray, members: list[str]) -> np.ndarray:
    return np.isin(np.asarray(groups_per_window), np.asarray(members))
