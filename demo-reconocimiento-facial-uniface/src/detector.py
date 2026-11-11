"""Detección facial con UniFace (RetinaFace): cajas, puntuación y 5 puntos clave."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .paths import setup_model_cache


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    score: float
    landmarks: np.ndarray  # (5, 2)


class FaceDetector:
    """Envoltorio de ``uniface.RetinaFace`` (pesos RetinaFace MNET_V2 por defecto)."""

    def __init__(self, confidence_threshold: float = 0.5, providers: list[str] | None = None):
        setup_model_cache()
        from uniface import RetinaFace  # import tardío: la caché debe fijarse antes

        self._model = RetinaFace(
            confidence_threshold=confidence_threshold,
            providers=providers or ["CPUExecutionProvider"],
        )

    def detect(self, image_bgr: np.ndarray) -> list[Detection]:
        faces = self._model.detect(image_bgr)
        out = []
        for f in faces:
            x1, y1, x2, y2 = (float(v) for v in f.bbox[:4])
            out.append(Detection((x1, y1, x2, y2), float(f.confidence), np.asarray(f.landmarks, dtype=np.float32)))
        out.sort(key=lambda d: (d.bbox[0], d.bbox[1]))
        return out
