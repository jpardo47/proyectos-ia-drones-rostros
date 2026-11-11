"""Validador de etiquetas YOLO (``clase cx cy w h`` normalizados) de las imagenes sinteticas.

Comprueba: 5 campos por linea, clase entera valida, valores en [0, 1], ancho/alto positivos,
caja completa dentro de la imagen, y -si hay PNG- que exista, que sea PNG y que la caja tenga
al menos 1 px. Solo stdlib.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import Optional

_EPS = 1e-6


def png_size(path: Path) -> Optional[tuple[int, int]]:
    """(ancho, alto) leyendo la cabecera IHDR; None si no es un PNG valido."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def validate_label_line(line: str, n_classes: Optional[int] = None) -> list[str]:
    """Errores de una linea de etiqueta; lista vacia = valida."""
    parts = line.split()
    if len(parts) != 5:
        return [f"se esperaban 5 campos y hay {len(parts)}"]
    errors: list[str] = []
    try:
        cls = int(parts[0])
        if cls < 0 or (n_classes is not None and cls >= n_classes):
            errors.append(f"clase fuera de rango: {cls}")
    except ValueError:
        errors.append(f"clase no entera: {parts[0]!r}")
    try:
        cx, cy, w, h = (float(x) for x in parts[1:])
    except ValueError:
        return errors + ["coordenadas no numericas"]
    for name, v in (("cx", cx), ("cy", cy), ("w", w), ("h", h)):
        if not (0.0 <= v <= 1.0):
            errors.append(f"{name}={v} fuera de [0, 1]")
    if w <= 0 or h <= 0:
        errors.append("ancho/alto deben ser > 0")
    if cx - w / 2 < -_EPS or cx + w / 2 > 1 + _EPS or cy - h / 2 < -_EPS or cy + h / 2 > 1 + _EPS:
        errors.append("la caja se sale de la imagen")
    return errors


def validate_label_file(label_path: Path, image_path: Optional[Path] = None,
                        n_classes: Optional[int] = 1) -> list[str]:
    errors: list[str] = []
    if not label_path.is_file():
        return [f"no existe la etiqueta {label_path.name}"]
    lines = [ln for ln in label_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        errors.append("etiqueta vacia")
    for i, ln in enumerate(lines, start=1):
        errors += [f"linea {i}: {e}" for e in validate_label_line(ln, n_classes)]
    if image_path is not None:
        size = png_size(image_path)
        if size is None:
            errors.append(f"imagen {image_path.name} ausente o no es PNG valido")
        elif not errors:
            for ln in lines:
                _, cx, cy, w, h = ln.split()
                if float(w) * size[0] < 1.0 or float(h) * size[1] < 1.0:
                    errors.append("la caja mide menos de 1 px")
    return errors


def find_pairs(directory: Path) -> list[tuple[Path, Path]]:
    """Pares (imagen.png, etiqueta.txt) por nombre base; ignora classes.txt."""
    pairs = []
    for img in sorted(directory.glob("*.png")):
        pairs.append((img, img.with_suffix(".txt")))
    return pairs


def validate_directory(directory: Path, n_classes: Optional[int] = 1) -> dict[str, list[str]]:
    """Mapa ``nombre_imagen -> errores`` (lista vacia = correcta)."""
    return {img.name: validate_label_file(lbl, img, n_classes) for img, lbl in find_pairs(directory)}


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("uso: python -m src.simulation.yolo_validator <carpeta>")
        return 2
    report = validate_directory(Path(args[0]))
    bad = 0
    for name, errs in report.items():
        print(f"{'OK ' if not errs else 'ERR'} {name} {'; '.join(errs)}")
        bad += bool(errs)
    print(f"{len(report) - bad}/{len(report)} etiquetas validas")
    return 1 if bad or not report else 0


if __name__ == "__main__":
    raise SystemExit(main())
