"""Predice un WAV: probabilidad por ventana, decisión agregada, umbral y versión del modelo.

  python scripts/predict.py --wav ruta/al/archivo.wav [--model modelos/audio_clf.joblib]
         [--export-jsonl resultados/observaciones.jsonl --station-id P2-ACUSTICA-01
          --timestamp 2026-11-11T12:00:00Z [--per-window]]

La salida JSON de la predicción es determinista (mismo WAV + mismo modelo -> misma salida).
Si se exportan observaciones sin --timestamp, se usa la hora UTC actual (campo no determinista).
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

from src.export.observations import DEFAULT_STATION_ID, export_jsonl, observations_from_prediction  # noqa: E402
from src.models.classifier import AudioClassifier  # noqa: E402
from src.pipeline import DEFAULT_MODEL_PATH, predict_wav  # noqa: E402


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", type=Path, required=True)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    ap.add_argument("--export-jsonl", type=Path, default=None)
    ap.add_argument("--station-id", default=DEFAULT_STATION_ID)
    ap.add_argument("--timestamp", default=None, help="ISO 8601 con zona, p. ej. 2026-11-11T12:00:00Z")
    ap.add_argument("--data-origin", choices=["replay", "simulation"], default=None,
                    help="por defecto: 'simulation' si el archivo se llama SIMULADO_*, si no 'replay'")
    ap.add_argument("--per-window", action="store_true")
    a = ap.parse_args(argv)
    if not a.model.exists():
        raise SystemExit(f"no existe el modelo {a.model}; entrena con scripts/train.py")
    model = AudioClassifier.load(a.model)
    pred = predict_wav(a.wav, model)
    pred["source"] = a.wav.name  # solo el nombre: salida independiente de la ruta local
    out = {"prediction": pred}
    if a.export_jsonl:
        obs = observations_from_prediction(pred, station_id=a.station_id, timestamp_utc=a.timestamp,
                                           data_origin=a.data_origin, per_window=a.per_window)
        export_jsonl(obs, a.export_jsonl, append=True)
        out["observations_exported"] = len(obs)
        out["observations_path"] = str(a.export_jsonl)
    print(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True))
    return out


if __name__ == "__main__":
    main()
