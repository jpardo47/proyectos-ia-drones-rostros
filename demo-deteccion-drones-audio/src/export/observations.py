"""Exportación de predicciones acústicas como observaciones del contrato P2 -> P3.

Contrato: `contracts/observation.schema.json` (v1.0.0). Reglas aplicadas aquí:
- sensor_type = "acoustic"; classification = "drone" | "no_drone"; classifier_score en [0, 1].
- latitude, longitude y altitude SIEMPRE null: la clasificación de audio no produce
  coordenadas, altura ni distancia.
- data_origin = "replay" (WAV de un dataset grabado) o "simulation" (audio sintético), con
  is_simulated coherente (true solo para "simulation").
- Cada observación se valida con jsonschema antes de exportarse (JSONL).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "observation.schema.json"
DEFAULT_STATION_ID = "P2-ACUSTICA-01"
_NS = uuid.UUID("6f1c2b0e-8a7d-4a43-9d0e-2f2a6c1d5b11")
VALID_ORIGINS = ("replay", "simulation")


class ObservationValidationError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_observation(obs: dict) -> None:
    errors = sorted(_validator().iter_errors(obs), key=lambda e: list(e.path))
    if errors:
        raise ObservationValidationError("; ".join(f"{list(e.path)}: {e.message}" for e in errors))
    # comprobación explícita de zona horaria (por si falta el validador de formato date-time)
    ts = datetime.fromisoformat(obs["timestamp_utc"].replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ObservationValidationError("timestamp_utc sin zona horaria")


def infer_data_origin(source: str | None) -> str:
    """'simulation' si el nombre del archivo está marcado SIMULADO; si no, 'replay'."""
    from src.audio.synthetic import SIMULATED_TAG

    return "simulation" if source and SIMULATED_TAG in Path(source).name.upper() else "replay"


def _fmt_ts(ts: datetime | str | None) -> str:
    if ts is None:
        ts = datetime.now(timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ObservationValidationError("timestamp sin zona horaria; usa UTC explícito")
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_observation(*, score: float, threshold: float, model_version: str,
                      station_id: str = DEFAULT_STATION_ID, timestamp_utc: datetime | str | None = None,
                      data_origin: str | None = None, source: str | None = None,
                      window: tuple[float, float] | None = None) -> dict:
    """Construye y valida una observación acústica. Lanza ObservationValidationError si no cumple."""
    origin = data_origin or infer_data_origin(source)
    if origin not in VALID_ORIGINS:
        raise ObservationValidationError(f"data_origin '{origin}' no permitido en P2 (usa {VALID_ORIGINS})")
    ts = _fmt_ts(timestamp_utc)
    score = float(min(1.0, max(0.0, score)))
    src_name = Path(source).name if source else "stream"
    ref = f"{src_name}|model={model_version}|thr={threshold:.2f}"
    if window is not None:
        ref += f"|win={window[0]:.2f}-{window[1]:.2f}s"
    obs = {
        "event_id": str(uuid.uuid5(_NS, f"{station_id}|{ts}|{ref}")),
        "station_id": station_id,
        "sensor_type": "acoustic",
        "timestamp_utc": ts,
        "data_origin": origin,
        "is_simulated": origin == "simulation",
        "object_id": None,
        "classification": "drone" if score >= threshold else "no_drone",
        "classifier_score": round(score, 6),
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "altitude_reference": None,
        "measurement_uncertainty": None,
        "sensor_quality": None,
        "raw_reference": ref[:512],
    }
    validate_observation(obs)
    return obs


def observations_from_prediction(pred: dict, *, station_id: str = DEFAULT_STATION_ID,
                                 timestamp_utc: datetime | str | None = None,
                                 data_origin: str | None = None, per_window: bool = False) -> list[dict]:
    """Convierte la salida de `src.pipeline.predict_wav` en observaciones validadas.

    Por defecto, una observación por archivo (decisión agregada). Con per_window=True, una por
    ventana con timestamp = inicio + desplazamiento de la ventana.
    """
    from datetime import timedelta

    base = _fmt_ts(timestamp_utc)
    base_dt = datetime.fromisoformat(base.replace("Z", "+00:00"))
    common = dict(threshold=pred["threshold"], model_version=pred["model_version"], station_id=station_id,
                  data_origin=data_origin, source=pred.get("source"))
    if not per_window:
        return [build_observation(score=pred["aggregate_probability"], timestamp_utc=base_dt, **common)]
    return [build_observation(score=w["probability"], timestamp_utc=base_dt + timedelta(seconds=w["start_s"]),
                              window=(w["start_s"], w["end_s"]), **common)
            for w in pred["windows"]]


def export_jsonl(observations: list[dict], path: str | Path, append: bool = False) -> Path:
    """Valida de nuevo cada observación y escribe JSONL (una por línea)."""
    for o in observations:
        validate_observation(o)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8", newline="\n") as f:
        for o in observations:
            f.write(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n")
    return path
