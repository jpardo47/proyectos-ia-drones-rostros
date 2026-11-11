"""Alineación (5 puntos) y embedding normalizado con UniFace (ArcFace MNET, 512-D)."""
from __future__ import annotations

import numpy as np

from .paths import setup_model_cache


class FaceEmbedder:
    def __init__(self, providers: list[str] | None = None):
        setup_model_cache()
        from uniface import ArcFace

        self._model = ArcFace(providers=providers or ["CPUExecutionProvider"])

    def embed(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        """Alinea el rostro con los puntos clave y devuelve un vector L2-normalizado (512,)."""
        emb = self._model.get_normalized_embedding(image_bgr, np.asarray(landmarks, dtype=np.float32))
        return np.asarray(emb, dtype=np.float32).ravel()
