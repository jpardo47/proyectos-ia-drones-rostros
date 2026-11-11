"""Entrena el clasificador drone/no_drone con división por grabación y umbral calibrado en validación.

Ejemplos (desde la raíz de P2):
  # prueba de humo con audio SINTÉTICO (SIMULADO)
  python scripts/train.py --synthetic
  # datos reales (etiquetas leídas del prefijo del nombre de archivo)
  python scripts/train.py --data-dir data/raw/DroneDetectionThesis \
      --rule prefix --label-map "{\"DRONE\":\"drone\",\"HELICOPTER\":\"no_drone\",\"BACKGROUND\":\"no_drone\"}"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from src.audio.features import FeatureConfig  # noqa: E402
from src.audio.synthetic import generate_synthetic_dataset  # noqa: E402
from src.dataset import build_manifest, featurize_manifest  # noqa: E402
from src.models.classifier import AudioClassifier  # noqa: E402
from src.models.metrics import window_and_recording_metrics  # noqa: E402
from src.models.splits import mask_for, split_groups  # noqa: E402
from src.models.threshold import calibrate_threshold  # noqa: E402

import pandas as pd  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true", help="genera y usa audio SINTÉTICO (SIMULADO)")
    src.add_argument("--data-dir", type=Path, help="carpeta con WAV reales")
    ap.add_argument("--label-map", default=None, help="JSON (texto o ruta) clase_original -> drone|no_drone")
    ap.add_argument("--rule", choices=["prefix", "folder"], default="prefix")
    ap.add_argument("--group-regex", default=None, help="regex con grupo 1 = id de grabación/sesión común")
    ap.add_argument("--model-kind", choices=["logreg", "rf"], default="logreg")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--window-s", type=float, default=1.0)
    ap.add_argument("--hop-s", type=float, default=0.5)
    ap.add_argument("--n-synthetic", type=int, default=12, help="grabaciones sintéticas por clase")
    ap.add_argument("--out-model", type=Path, default=None)
    ap.add_argument("--results-dir", type=Path, default=None)
    return ap.parse_args(argv)


def load_label_map(s: str | None) -> dict:
    if not s:
        raise SystemExit("--label-map es obligatorio con --data-dir (no se suponen clases)")
    p = Path(s)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else json.loads(s)


def main(argv=None) -> dict:
    a = parse_args(argv)
    cfg = FeatureConfig(window_s=a.window_s, hop_s=a.hop_s)
    if a.synthetic:
        origin = "simulation"
        out_model = a.out_model or ROOT / "modelos" / "SIMULADO_audio_clf.joblib"
        res_dir = a.results_dir or ROOT / "resultados" / "simulado"
        rows = generate_synthetic_dataset(ROOT / "data" / "interim" / "sintetico", n_per_class=a.n_synthetic,
                                          seed=a.seed)
        df = pd.DataFrame(rows)
        df["source_class"] = df["label"].str.upper()
        summary = {"root": "data/interim/sintetico (SIMULADO)", "rule": "synthetic", "n_files": len(df),
                   "files_per_label": df["label"].value_counts().sort_index().to_dict(),
                   "groups_per_label": df.groupby("label")["group"].nunique().sort_index().to_dict(),
                   "excluded_source_classes": {}}
    else:
        origin = "replay"
        out_model = a.out_model or ROOT / "modelos" / "audio_clf.joblib"
        res_dir = a.results_dir or ROOT / "resultados"
        df, summary = build_manifest(a.data_dir, load_label_map(a.label_map), a.rule, a.group_regex, origin)
        if df.empty:
            raise SystemExit(f"no hay archivos etiquetados en {a.data_dir}: {summary}")
        for lab in ("drone", "no_drone"):
            if summary["groups_per_label"].get(lab, 0) < 3:
                raise SystemExit(f"BLOQUEADO: clase '{lab}' con <3 grabaciones; no se fabrican negativos. {summary}")
    res_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(res_dir / "manifest.csv", index=False)

    print(f"[train] origen={origin} archivos={len(df)} por etiqueta={summary['files_per_label']}")
    X, y, groups, info = featurize_manifest(df, cfg)
    # estratificación por clase ORIGINAL (p. ej. DRONE/HELICOPTER/BACKGROUND), a nivel de grabación
    classes = sorted(df["source_class"].unique())
    strata = {str(g): classes.index(sc) for g, sc in zip(df["group"], df["source_class"])}
    split = split_groups(list(groups), {g: strata[str(g)] for g in set(groups)}, a.val_frac, a.test_frac, a.seed)
    tr, va = mask_for(groups, split["train"]), mask_for(groups, split["val"])

    model = AudioClassifier(a.model_kind, a.seed, cfg)
    model.fit(X[tr], y[tr])
    thr, thr_info = calibrate_threshold(y[va], model.predict_proba(X[va]))
    model.threshold = thr
    val_metrics = window_and_recording_metrics(groups[va], y[va], model.predict_proba(X[va]), thr)
    model.metadata = {
        "data_origin": origin, "is_simulated": origin == "simulation", "seed": a.seed,
        "dataset_summary": summary, "threshold_calibration": thr_info,
        "split_sizes": {k: len(v) for k, v in split.items()},
        "n_windows": {k: int(mask_for(groups, v).sum()) for k, v in split.items()},
    }
    model.save(out_model)
    np.savez_compressed(res_dir / "features_cache.npz", X=X, y=y, groups=groups.astype(str))
    (res_dir / "split.json").write_text(json.dumps({
        "seed": a.seed, "data_origin": origin, "model_path": str(out_model), "model_version": model.model_version,
        "threshold": thr, "split": split, "dataset_summary": summary, "val_metrics": val_metrics,
        "feature_config": cfg.to_dict(), "files": info,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tag = " [SIMULADO]" if origin == "simulation" else ""
    print(f"[train]{tag} modelo={model.model_version} umbral={thr:.2f} "
          f"grabaciones train/val/test={[len(split[k]) for k in ('train', 'val', 'test')]}")
    print(f"[train]{tag} val por grabación F1={val_metrics['per_recording']['f1']} -> {out_model}")
    return {"model_path": str(out_model), "results_dir": str(res_dir), "model_version": model.model_version}


if __name__ == "__main__":
    main()
