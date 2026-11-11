"""API FastAPI mínima del clasificador acústico (P2).

  GET  /health   -> estado y versión del modelo cargado
  POST /predict  -> multipart con campo `file` (WAV); parámetros de consulta opcionales:
                    station_id, timestamp_utc (ISO 8601 con zona), data_origin (replay|simulation)
                    Respuesta: predicción + observación exportable (contrato P2 -> P3).

Arranque:  python app.py  [--host 127.0.0.1 --port 8002 --model modelos/audio_clf.joblib]
Modelo: variable de entorno P2_MODEL_PATH o modelos/audio_clf.joblib.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from src.export.observations import DEFAULT_STATION_ID, ObservationValidationError, observations_from_prediction
from src.models.classifier import AudioClassifier
from src.pipeline import DEFAULT_MODEL_PATH, predict_wav_bytes

MAX_BYTES = 50 * 1024 * 1024


def create_app(model_path: str | Path | None = None) -> FastAPI:
    path = Path(model_path or os.environ.get("P2_MODEL_PATH", DEFAULT_MODEL_PATH))
    app = FastAPI(title="P2 — clasificador acústico drone/no_drone", version="1.0.0")
    state: dict = {"model": None, "path": path, "error": None}
    try:
        state["model"] = AudioClassifier.load(path)
    except Exception as exc:  # el servicio arranca igualmente y /health informa
        state["error"] = f"{type(exc).__name__}: {exc}"

    @app.get("/health")
    def health():
        m = state["model"]
        return {"status": "ok" if m else "sin_modelo", "model_loaded": m is not None,
                "model_version": m.model_version if m else None,
                "model_data_origin": m.metadata.get("data_origin") if m else None,
                "threshold": m.threshold if m else None, "error": state["error"]}

    @app.post("/predict")
    async def predict(file: UploadFile = File(...),
                      station_id: str = Query(DEFAULT_STATION_ID, min_length=1, max_length=64),
                      timestamp_utc: str | None = Query(None),
                      data_origin: str | None = Query(None, pattern="^(replay|simulation)$")):
        m = state["model"]
        if m is None:
            raise HTTPException(503, f"modelo no cargado ({state['error']})")
        raw = await file.read()
        if not raw or len(raw) > MAX_BYTES:
            raise HTTPException(400, "archivo vacío o demasiado grande")
        try:
            pred = predict_wav_bytes(raw, m, source=Path(file.filename or "upload.wav").name)
        except Exception as exc:
            raise HTTPException(400, f"no se pudo leer el audio: {type(exc).__name__}") from exc
        try:
            obs = observations_from_prediction(pred, station_id=station_id, timestamp_utc=timestamp_utc,
                                               data_origin=data_origin)[0]
        except (ObservationValidationError, ValueError) as exc:
            raise HTTPException(422, f"observación inválida: {exc}") from exc
        return {"prediction": pred, "observation": obs}

    return app


app = create_app()

if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    uvicorn.run(create_app(a.model), host=a.host, port=a.port)
