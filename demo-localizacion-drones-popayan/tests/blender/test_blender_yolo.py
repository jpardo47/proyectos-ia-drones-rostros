"""Validacion de etiquetas YOLO. La parte sobre imagenes de Blender se salta si no se generaron."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from src.simulation.yolo_validator import (
    png_size,
    validate_directory,
    validate_label_file,
    validate_label_line,
)

BLENDER_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "examples" / "blender"


def _write_png(path: Path, w: int, h: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_linea_valida():
    assert validate_label_line("0 0.5 0.5 0.2 0.1") == []


@pytest.mark.parametrize("line", [
    "0 0.5 0.5 0.2",            # faltan campos
    "x 0.5 0.5 0.2 0.1",        # clase no entera
    "0 1.2 0.5 0.2 0.1",        # fuera de [0, 1]
    "0 0.95 0.5 0.2 0.1",       # caja fuera de la imagen
    "0 0.5 0.5 0 0.1",          # ancho cero
    "3 0.5 0.5 0.2 0.1",        # clase inexistente (1 clase)
    "0 a b c d",                # no numerico
])
def test_lineas_invalidas(line):
    assert validate_label_line(line, n_classes=1) != []


def test_archivo_con_png_sintetico(tmp_path):
    img, lbl = tmp_path / "a.png", tmp_path / "a.txt"
    _write_png(img, 64, 48)
    assert png_size(img) == (64, 48)
    lbl.write_text("0 0.5 0.5 0.25 0.25\n")
    assert validate_label_file(lbl, img) == []
    lbl.write_text("0 0.5 0.5 0.001 0.001\n")      # < 1 px
    assert validate_label_file(lbl, img) != []
    lbl.write_text("")
    assert validate_label_file(lbl, img) != []
    assert validate_label_file(tmp_path / "no.txt") != []
    (tmp_path / "b.png").write_bytes(b"no soy png")
    assert png_size(tmp_path / "b.png") is None


def test_directorio(tmp_path):
    _write_png(tmp_path / "ok.png", 32, 32)
    (tmp_path / "ok.txt").write_text("0 0.5 0.5 0.5 0.5\n")
    _write_png(tmp_path / "mal.png", 32, 32)
    (tmp_path / "mal.txt").write_text("0 0.9 0.5 0.5 0.5\n")
    rep = validate_directory(tmp_path)
    assert rep["ok.png"] == [] and rep["mal.png"] != []


def test_imagenes_blender_generadas():
    pngs = sorted(BLENDER_DIR.glob("*.png")) if BLENDER_DIR.is_dir() else []
    if not pngs:
        pytest.skip("no hay imagenes de Blender generadas (ejecutar blender/generate_scene.py)")
    report = validate_directory(BLENDER_DIR)
    assert report and all(not errs for errs in report.values()), report
    for p in pngs:
        assert png_size(p) == (640, 480)
