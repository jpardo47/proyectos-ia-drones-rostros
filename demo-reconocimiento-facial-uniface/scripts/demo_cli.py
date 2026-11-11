"""Demo por línea de comandos.

Uso:
    python scripts/demo_cli.py --image foto.jpg [--gallery datasets/galeria] [--threshold 0.4] --out resultados/demo.csv

Sin --image se usa una imagen de muestra de dominio público (skimage.data.astronaut, NASA).
Solo deben usarse fotografías con autorización.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.export import results_to_dataframe, write_csv  # noqa: E402
from src.matcher import DEFAULT_THRESHOLD  # noqa: E402
from src.paths import DEFAULT_GALLERY, RESULTS_DIR, SAMPLES_DIR  # noqa: E402


def ensure_sample() -> Path:
    """Guarda la imagen de muestra (astronauta, NASA, dominio público) en datasets/muestras/."""
    path = SAMPLES_DIR / "astronaut_nasa.jpg"
    if not path.exists():
        from skimage import data

        SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="ruta de la imagen (por defecto, muestra de dominio público)")
    ap.add_argument("--gallery", default=str(DEFAULT_GALLERY), help="carpeta galeria/<nombre>/*.jpg")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="umbral de similitud coseno")
    ap.add_argument("--out", default=str(RESULTS_DIR / "demo.csv"), help="CSV de salida")
    ap.add_argument("--annotated", help="guardar además la imagen anotada en esta ruta")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from src.detector import FaceDetector
    from src.embedder import FaceEmbedder
    from src.gallery import enroll_from_folder
    from src.pipeline import FacePipeline, draw_results

    image_path = Path(args.image) if args.image else ensure_sample()
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"ERROR: no se pudo leer la imagen {image_path}", file=sys.stderr)
        return 2

    detector, embedder = FaceDetector(), FaceEmbedder()
    gallery, warns = enroll_from_folder(args.gallery, detector, embedder)
    for w in warns:
        print(f"AVISO: {w}", file=sys.stderr)
    print(f"Galería: {len(gallery)} imágenes, identidades: {gallery.identities or 'ninguna (todo sera desconocido)'}")

    results = FacePipeline(detector, embedder, gallery, args.threshold).process(img)
    df = results_to_dataframe(image_path.name, results)
    out = write_csv(df, args.out)
    if args.annotated:
        cv2.imwrite(args.annotated, draw_results(img, results))

    print(f"Imagen: {image_path}  rostros detectados: {len(results)}")
    for r in results:
        print(f"  rostro {r.index}: caja={[round(v) for v in r.bbox]} score={r.detection_score:.3f} "
              f"-> {r.match.identity} (similitud={r.match.similarity:.3f}, umbral={r.match.threshold})")
    print(f"CSV escrito en {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
