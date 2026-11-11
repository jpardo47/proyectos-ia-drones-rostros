"""Comprueba las etiquetas YOLO de Blender contra los PÍXELES de la imagen renderizada.

``yolo_validator`` valida el formato. Esta prueba valida el contenido: localiza el dron en la
imagen por su color (cuerpo naranja, brazos y rotores oscuros) y exige que la caja etiquetada lo
encierre de forma ajustada. Se salta si no hay imágenes (hay que ejecutar antes
``blender/generate_scene.py``) o si falta Pillow.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

Image = pytest.importorskip("PIL.Image")

BLENDER_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "examples" / "blender"
PNGS = sorted(BLENDER_DIR.glob("drone_*.png")) if BLENDER_DIR.is_dir() else []

MARGEN_BUSQUEDA_PX = 6   # se busca el dron en la caja etiquetada ampliada este margen
TOLERANCIA_BORDE_PX = 4  # cada borde de la caja debe quedar a esta distancia, como máximo, del dron


def _caja_px(etiqueta: Path, ancho: int, alto: int) -> tuple[float, float, float, float]:
    clase, cx, cy, w, h = etiqueta.read_text(encoding="utf-8").split()
    assert clase == "0"
    cx, cy, w, h = float(cx) * ancho, float(cy) * alto, float(w) * ancho, float(h) * alto
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _mascaras(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    naranja = (r > 140) & (r - b > 80) & (g - b > 30)   # cuerpo del dron
    oscuro = np.maximum(np.maximum(r, g), b) < 110       # brazos y rotores
    return naranja, oscuro


@pytest.mark.skipif(not PNGS, reason="no hay imagenes de Blender generadas (ejecutar blender/generate_scene.py)")
@pytest.mark.parametrize("png", PNGS, ids=lambda p: p.name)
def test_la_caja_encierra_al_dron_renderizado(png: Path) -> None:
    rgb = np.asarray(Image.open(png).convert("RGB"))
    alto, ancho = rgb.shape[:2]
    x0, y0, x1, y1 = _caja_px(png.with_suffix(".txt"), ancho, alto)
    naranja, oscuro = _mascaras(rgb)

    # 1) El cuerpo naranja existe y no hay naranja fuera de la caja.
    ys, xs = np.nonzero(naranja)
    assert len(xs) >= 4, "no se encontró el cuerpo naranja del dron en la imagen"
    assert xs.min() >= x0 - 2 and xs.max() <= x1 + 2 and ys.min() >= y0 - 2 and ys.max() <= y1 + 2, (
        f"hay píxeles del cuerpo del dron fuera de la caja etiquetada: "
        f"naranja x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}] caja ({x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f})"
    )

    # 2) La caja es ajustada: el dron (naranja u oscuro) llega cerca de cada borde.
    m = MARGEN_BUSQUEDA_PX
    ventana = np.zeros_like(naranja)
    ventana[max(int(y0) - m, 0): int(y1) + m + 1, max(int(x0) - m, 0): int(x1) + m + 1] = True
    ys, xs = np.nonzero((naranja | oscuro) & ventana)
    assert len(xs) >= 20, "muy pocos píxeles del dron dentro de la caja etiquetada"
    desvios = {
        "izquierda": abs(xs.min() - x0), "derecha": abs(xs.max() - x1),
        "arriba": abs(ys.min() - y0), "abajo": abs(ys.max() - y1),
    }
    assert max(desvios.values()) <= TOLERANCIA_BORDE_PX, f"caja desajustada respecto al dron: {desvios}"
