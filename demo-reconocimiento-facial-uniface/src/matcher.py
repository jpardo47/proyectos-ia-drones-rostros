"""Comparador por similitud coseno contra la galería, con umbral configurable."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

UNKNOWN = "desconocido"
DEFAULT_THRESHOLD = 0.4


@dataclass
class MatchResult:
    identity: str  # nombre o "desconocido"
    similarity: float  # mejor similitud coseno (nan si la galería está vacía)
    best_candidate: str | None  # identidad más parecida aunque no supere el umbral
    threshold: float


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(_normalize(a).ravel() @ _normalize(b).ravel())


def match(embedding: np.ndarray, gallery_embeddings: np.ndarray, gallery_labels: list[str],
          threshold: float = DEFAULT_THRESHOLD) -> MatchResult:
    """Devuelve la identidad si la similitud coseno máxima >= umbral; si no, ``desconocido``."""
    if gallery_embeddings is None or len(gallery_labels) == 0 or len(gallery_embeddings) == 0:
        return MatchResult(UNKNOWN, float("nan"), None, threshold)
    sims = _normalize(gallery_embeddings) @ _normalize(embedding).ravel()
    # similitud por identidad = máximo entre sus imágenes de referencia
    best_by_id: dict[str, float] = {}
    for label, s in zip(gallery_labels, sims):
        best_by_id[label] = max(float(s), best_by_id.get(label, -2.0))
    cand = max(best_by_id, key=best_by_id.get)
    sim = best_by_id[cand]
    return MatchResult(cand if sim >= threshold else UNKNOWN, sim, cand, threshold)
