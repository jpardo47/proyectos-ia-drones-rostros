"""Pipeline imagen -> lista de resultados (detección + embedding + comparación)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gallery import Gallery
from .matcher import DEFAULT_THRESHOLD, UNKNOWN, MatchResult, match


@dataclass
class FaceResult:
    index: int
    bbox: tuple[float, float, float, float]
    detection_score: float
    match: MatchResult
    landmarks: np.ndarray


class FacePipeline:
    def __init__(self, detector, embedder, gallery: Gallery | None = None, threshold: float = DEFAULT_THRESHOLD):
        self.detector, self.embedder = detector, embedder
        self.gallery = gallery or Gallery()
        self.threshold = threshold

    def process(self, image_bgr: np.ndarray, threshold: float | None = None) -> list[FaceResult]:
        thr = self.threshold if threshold is None else threshold
        results = []
        for i, det in enumerate(self.detector.detect(image_bgr)):
            emb = self.embedder.embed(image_bgr, det.landmarks)
            m = match(emb, self.gallery.embeddings, self.gallery.labels, thr)
            results.append(FaceResult(i, det.bbox, det.score, m, det.landmarks))
        return results


def draw_results(image_bgr: np.ndarray, results: list[FaceResult]) -> np.ndarray:
    """Devuelve una copia con cajas y etiquetas dibujadas."""
    import cv2

    out = image_bgr.copy()
    for r in results:
        x1, y1, x2, y2 = (int(v) for v in r.bbox)
        known = r.match.identity != UNKNOWN
        color = (0, 160, 0) if known else (0, 0, 220)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        sim = "" if np.isnan(r.match.similarity) else f" {r.match.similarity:.2f}"
        cv2.putText(out, f"#{r.index} {r.match.identity}{sim}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        for px, py in r.landmarks:
            cv2.circle(out, (int(px), int(py)), 2, (255, 200, 0), -1)
    return out
