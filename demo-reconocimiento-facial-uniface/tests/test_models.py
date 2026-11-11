"""Pruebas de integración con pesos reales de UniFace.

Se saltan limpiamente si los pesos no están en ``modelos/`` y no se pueden descargar.
Imagen: skimage.data.astronaut() (NASA, dominio público).
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def models():
    try:
        from src.detector import FaceDetector
        from src.embedder import FaceEmbedder

        return FaceDetector(), FaceEmbedder()
    except Exception as exc:  # pesos ausentes / sin red
        pytest.skip(f"Pesos de UniFace no disponibles: {exc}")


@pytest.fixture(scope="module")
def astronaut():
    skimage = pytest.importorskip("skimage")
    from skimage import data

    return cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)


def test_detector_finds_face(models, astronaut):
    det, _ = models
    faces = det.detect(astronaut)
    assert len(faces) >= 1
    f = faces[0]
    assert 0.5 <= f.score <= 1.0 and f.landmarks.shape == (5, 2)
    x1, y1, x2, y2 = f.bbox
    assert x2 > x1 and y2 > y1


def test_embedding_normalized_and_self_match(models, astronaut):
    from src.gallery import Gallery
    from src.matcher import UNKNOWN, match

    det, emb = models
    f = det.detect(astronaut)[0]
    e = emb.embed(astronaut, f.landmarks)
    assert e.shape == (512,) and np.linalg.norm(e) == pytest.approx(1.0, abs=1e-4)
    g = Gallery(); g.add("astronauta", e)
    assert match(e, g.embeddings, g.labels, 0.4).identity == "astronauta"
    assert match(e, Gallery().embeddings, [], 0.4).identity == UNKNOWN


def test_blank_image_has_no_faces(models):
    det, _ = models
    assert det.detect(np.full((240, 320, 3), 127, np.uint8)) == []
