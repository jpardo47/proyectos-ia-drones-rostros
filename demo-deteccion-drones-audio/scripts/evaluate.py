"""Evalúa el modelo en el conjunto de TEST (grabaciones nunca vistas) y escribe métricas + reporte.

  python scripts/evaluate.py                      # datos reales -> resultados/metricas.json, docs/reporte-metricas.md
  python scripts/evaluate.py --results-dir resultados/simulado --out-json resultados/simulado/metricas_SIMULADO.json \
      --out-md docs/reporte-metricas-SIMULADO.md  # prueba de humo SIMULADA
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from src.models.classifier import AudioClassifier  # noqa: E402
from src.models.metrics import window_and_recording_metrics  # noqa: E402
from src.models.splits import mask_for  # noqa: E402


def _cm_table(m: dict) -> str:
    (tn, fp), (fn, tp) = m["confusion_matrix"]["matrix"]
    return ("| real \\ predicho | no_drone | drone |\n|---|---|---|\n"
            f"| no_drone | {tn} | {fp} |\n| drone | {fn} | {tp} |")


def _row(name: str, m: dict) -> str:
    return (f"| {name} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['specificity']:.3f} | "
            f"{m['accuracy']:.3f} | {m['support_pos']} | {m['support_neg']} |")


def render_report(res: dict, notes: str | None) -> str:
    sim = res["data_origin"] == "simulation"
    tag = "SIMULADO" if sim else "IMPLEMENTADO_Y_PROBADO (datos reales)"
    t, v = res["test"], res["val"]
    ds = res["dataset_summary"]
    lines = [
        f"# Reporte de métricas — P2 clasificador acústico drone / no_drone",
        "",
        f"**Estado: {tag}**",
        "",
    ]
    if sim:
        lines += ["> **SIMULADO.** Estas cifras provienen de audio SINTÉTICO generado por "
                  "`src/audio/synthetic.py` (tonos armónicos + ruido). Solo demuestran que el pipeline "
                  "funciona de extremo a extremo. **No son rendimiento real** y no deben citarse como tal.", ""]
    lines += [
        f"- Generado: {res['generated_utc']} · modelo `{res['model_version']}` ({res['model_kind']}) · semilla {res['seed']}",
        f"- Origen de datos: `{res['data_origin']}` · raíz: `{ds.get('root')}` · regla de etiquetas: `{ds.get('rule')}`",
        f"- Archivos por clase original: `{ds.get('files_per_source_class', ds.get('files_per_label'))}`",
        f"- Archivos por etiqueta binaria: `{ds.get('files_per_label')}` · grabaciones por etiqueta: `{ds.get('groups_per_label')}`",
        f"- Clases excluidas (sin mapear): `{ds.get('excluded_source_classes')}`",
        f"- Ventana {res['feature_config']['window_s']} s, salto {res['feature_config']['hop_s']} s, "
        f"{res['feature_config']['sample_rate']} Hz, {res['feature_config']['n_mels']} bandas mel, "
        f"{res['feature_config']['n_mfcc']} MFCC",
        "",
        "## División por grabación (sin fuga entre particiones)",
        "",
        "| partición | grabaciones | ventanas | grabaciones drone | grabaciones no_drone |",
        "|---|---|---|---|---|",
    ]
    for k in ("train", "val", "test"):
        s = res["split_counts"][k]
        lines.append(f"| {k} | {s['recordings']} | {s['windows']} | {s['recordings_drone']} | {s['recordings_no_drone']} |")
    lines += [
        "",
        f"Umbral calibrado en validación (máx. F1 por ventana): **{res['threshold']:.2f}**. "
        "Decisión por grabación = media de probabilidades de sus ventanas ≥ umbral.",
        "",
        "## Resultados en TEST" + (" (SIMULADO)" if sim else ""),
        "",
        f"> Precaución: el test tiene solo {t['n_recordings']} grabaciones; las cifras dependen mucho de la "
        "división. Si hay una sección de sensibilidad a la semilla al final, esa es la estimación más representativa.",
        "",
        "| nivel | precisión | recall | F1 | especificidad | exactitud | n drone | n no_drone |",
        "|---|---|---|---|---|---|---|---|",
        _row("por ventana", t["per_window"]),
        _row("por grabación", t["per_recording"]),
        "",
        "Matriz de confusión por ventana:",
        "",
        _cm_table(t["per_window"]),
        "",
        "Matriz de confusión por grabación:",
        "",
        _cm_table(t["per_recording"]),
        "",
    ]
    if res.get("test_by_source_class"):
        lines += ["Desglose en test por clase original (decisión por grabación):", "",
                  "| clase original | grabaciones | predichas drone | prob. media |", "|---|---|---|---|"]
        for sc, d in sorted(res["test_by_source_class"].items()):
            lines.append(f"| {sc} | {d['recordings']} | {d['predicted_drone']} | {d['mean_probability']:.3f} |")
        lines.append("")
    lines += [
        "## Validación (usada para elegir el umbral; no es una estimación independiente)",
        "",
        "| nivel | precisión | recall | F1 | especificidad | exactitud | n drone | n no_drone |",
        "|---|---|---|---|---|---|---|---|",
        _row("por ventana", v["per_window"]),
        _row("por grabación", v["per_recording"]),
        "",
        "## Límites generales",
        "",
        "- La clasificación de audio **no produce coordenadas, altura ni distancia**; las observaciones "
        "exportadas llevan `latitude`, `longitude` y `altitude` = null.",
        "- El conjunto de test es pequeño: una o dos grabaciones mal clasificadas cambian mucho las métricas "
        "por grabación. No hay intervalos de confianza.",
        "- Las ventanas de una misma grabación están correlacionadas; las métricas por ventana son optimistas "
        "respecto a su número efectivo de muestras.",
        "- El modelo solo conoce las condiciones de grabación, micrófonos y tipos de dron/ruido presentes en "
        "el conjunto de entrenamiento; no se ha evaluado en campo ni en Popayán.",
        f"- Entorno: Python {platform.python_version()}, CPU.",
    ]
    if notes:
        lines += ["", notes.strip()]
    return "\n".join(lines) + "\n"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", type=Path, default=ROOT / "resultados")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--notes", type=Path, default=None, help="markdown adicional (sesgos del dataset)")
    a = ap.parse_args(argv)
    meta = json.loads((a.results_dir / "split.json").read_text(encoding="utf-8"))
    sim = meta["data_origin"] == "simulation"
    out_json = a.out_json or (a.results_dir / ("metricas_SIMULADO.json" if sim else "metricas.json"))
    out_md = a.out_md or ROOT / "docs" / ("reporte-metricas-SIMULADO.md" if sim else "reporte-metricas.md")
    model = AudioClassifier.load(meta["model_path"])
    cache = np.load(a.results_dir / "features_cache.npz", allow_pickle=False)
    X, y, groups = cache["X"], cache["y"], cache["groups"]
    split = meta["split"]

    counts, evals = {}, {}
    for k in ("train", "val", "test"):
        m = mask_for(groups, split[k])
        rec_lab = {g: int(l) for g, l in zip(groups[m], y[m])}
        counts[k] = {"recordings": len(split[k]), "windows": int(m.sum()),
                     "recordings_drone": sum(v == 1 for v in rec_lab.values()),
                     "recordings_no_drone": sum(v == 0 for v in rec_lab.values())}
        if k != "train":
            evals[k] = window_and_recording_metrics(groups[m], y[m], model.predict_proba(X[m]), model.threshold)
    res = {
        "status": "SIMULADO" if sim else "REAL",
        "data_origin": meta["data_origin"], "is_simulated": sim,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "model_version": model.model_version, "model_kind": model.kind, "seed": meta["seed"],
        "threshold": model.threshold, "feature_config": meta["feature_config"],
        "dataset_summary": meta["dataset_summary"], "split_counts": counts,
        "test": evals["test"], "val": evals["val"],
        "test_recordings": split["test"],
    }
    # desglose por clase original en test (p. ej. HELICOPTER vs BACKGROUND como negativos)
    man_path = a.results_dir / "manifest.csv"
    if man_path.exists():
        import pandas as pd

        man = pd.read_csv(man_path)
        src_of = dict(zip(man["group"].astype(str), man["source_class"].astype(str)))
        mt = mask_for(groups, split["test"])
        p = model.predict_proba(X[mt])
        g_t = groups[mt]
        per_cls: dict = {}
        for g in sorted(set(g_t.tolist())):
            sc = src_of.get(g, "?")
            prob = float(p[g_t == g].mean())
            d = per_cls.setdefault(sc, {"recordings": 0, "predicted_drone": 0, "mean_probability": []})
            d["recordings"] += 1
            d["predicted_drone"] += int(prob >= model.threshold)
            d["mean_probability"].append(prob)
        for d in per_cls.values():
            d["mean_probability"] = round(float(np.mean(d["mean_probability"])), 4)
        res["test_by_source_class"] = per_cls
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    notes = a.notes.read_text(encoding="utf-8") if a.notes and a.notes.exists() else None
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_report(res, notes), encoding="utf-8")
    tag = "[SIMULADO] " if sim else ""
    tw, tr = res["test"]["per_window"], res["test"]["per_recording"]
    print(f"[evaluate] {tag}test ventana P={tw['precision']} R={tw['recall']} F1={tw['f1']} | "
          f"grabación P={tr['precision']} R={tr['recall']} F1={tr['f1']} (n={res['test']['n_recordings']})")
    print(f"[evaluate] -> {out_json} ; {out_md}")
    return res


if __name__ == "__main__":
    main()
