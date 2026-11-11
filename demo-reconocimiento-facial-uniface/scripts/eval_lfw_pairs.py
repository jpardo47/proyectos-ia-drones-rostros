"""Evaluación acotada de verificación facial con pares de LFW (pairsDevTest.txt).

Toma N/2 pares positivos y N/2 negativos (los primeros de cada bloque), calcula la similitud coseno
con UniFace (RetinaFace + ArcFace MNET) y reporta exactitud al umbral por defecto, el mejor umbral
y una exactitud con validación cruzada de 2 particiones (umbral elegido en una mitad, probado en la otra).

Uso:
    python scripts/eval_lfw_pairs.py [--lfw data/raw/lfw] [--n-pairs 200] [--out resultados/eval_lfw.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.matcher import DEFAULT_THRESHOLD, cosine_similarity  # noqa: E402


def read_pairs(pairs_file: Path):
    lines = pairs_file.read_text(encoding="utf-8").split("\n")
    lines = [ln.split() for ln in lines if ln.strip()]
    n = int(lines[0][0])
    pos = [(a, int(i), a, int(j), 1) for a, i, j in (x for x in lines[1:1 + n] if len(x) == 3)]
    neg = [(a, int(i), b, int(j), 0) for a, i, b, j in (x for x in lines[1 + n:1 + 2 * n] if len(x) == 4)]
    return pos, neg


def img_path(root: Path, name: str, idx: int) -> Path:
    return root / name / f"{name}_{idx:04d}.jpg"


def best_threshold(sims: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    cands = np.unique(np.concatenate([sims, [0.0, 1.0]]))
    accs = [((sims >= t) == labels.astype(bool)).mean() for t in cands]
    k = int(np.argmax(accs))
    return float(cands[k]), float(accs[k])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lfw", default=str(ROOT / "data" / "raw" / "lfw"))
    ap.add_argument("--n-pairs", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "resultados" / "eval_lfw.json"))
    args = ap.parse_args(argv)

    lfw = Path(args.lfw)
    pairs_file, img_root = lfw / "pairsDevTest.txt", lfw / "lfw_funneled"
    if not pairs_file.exists() or not img_root.exists():
        print(f"LFW no disponible en {lfw}: PREPARADO_NO_EJECUTADO", file=sys.stderr)
        return 3

    from src.detector import FaceDetector
    from src.embedder import FaceEmbedder

    det, emb = FaceDetector(), FaceEmbedder()
    cache: dict[Path, np.ndarray | None] = {}

    def embed(p: Path):
        if p not in cache:
            img = cv2.imread(str(p))
            faces = det.detect(img) if img is not None else []
            if not faces:
                cache[p] = None
            else:
                best = max(faces, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
                cache[p] = emb.embed(img, best.landmarks)
        return cache[p]

    pos, neg = read_pairs(pairs_file)
    half = args.n_pairs // 2
    # intercalar positivos y negativos para que ambas mitades de la validación cruzada estén equilibradas
    pairs = [p for pn in zip(pos[:half], neg[:half]) for p in pn]

    sims, labels, skipped = [], [], 0
    for a, i, b, j, y in pairs:
        ea, eb = embed(img_path(img_root, a, i)), embed(img_path(img_root, b, j))
        if ea is None or eb is None:
            skipped += 1
            continue
        sims.append(cosine_similarity(ea, eb))
        labels.append(y)
    sims, labels = np.array(sims), np.array(labels)
    n_eval = len(sims)

    acc_default = float(((sims >= DEFAULT_THRESHOLD) == labels.astype(bool)).mean())
    thr_best, acc_best = best_threshold(sims, labels)
    # validación cruzada de 2 particiones (pares pares/impares)
    idx = np.arange(n_eval)
    # los pares están intercalados (pos, neg, pos, neg...): agrupar de 2 en 2 mantiene ambas particiones equilibradas
    folds = [idx[(idx // 2) % 2 == 0], idx[(idx // 2) % 2 == 1]]
    cv_hits = 0
    for k in range(2):
        tr, te = folds[k], folds[1 - k]
        t, _ = best_threshold(sims[tr], labels[tr])
        cv_hits += int(((sims[te] >= t) == labels[te].astype(bool)).sum())
    acc_cv = cv_hits / n_eval
    # exactitud conservadora: pares sin rostro detectado cuentan como error
    acc_default_conservative = float(((sims >= DEFAULT_THRESHOLD) == labels.astype(bool)).sum()) / max(1, len(pairs))

    report = {
        "fuente": "LFW pairsDevTest.txt (primeros pares positivos y negativos)",
        "modelos": "uniface RetinaFace MNET_V2 + ArcFace MNET",
        "pares_solicitados": len(pairs), "pares_evaluados": n_eval, "pares_sin_rostro_omitidos": skipped,
        "positivos_evaluados": int(labels.sum()), "negativos_evaluados": int((1 - labels).sum()),
        "umbral_por_defecto": DEFAULT_THRESHOLD,
        "exactitud_umbral_por_defecto": round(acc_default, 4),
        "exactitud_umbral_por_defecto_sin_rostro_como_error": round(acc_default_conservative, 4),
        "mejor_umbral_en_muestra": round(thr_best, 4),
        "exactitud_mejor_umbral_en_muestra_optimista": round(acc_best, 4),
        "exactitud_validacion_cruzada_2_particiones": round(acc_cv, 4),
        "similitud_media_positivos": round(float(sims[labels == 1].mean()), 4),
        "similitud_media_negativos": round(float(sims[labels == 0].mean()), 4),
        "advertencia": "Evaluación acotada (pocos pares); no es el protocolo completo de 10 particiones de LFW.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
