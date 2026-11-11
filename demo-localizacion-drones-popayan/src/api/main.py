"""API REST de la demo de localizacion multisensor (P3). Datos SIMULADOS.

Lectura abierta; escritura y revision protegidas con la cabecera ``X-API-Token``
(comparada con ``POPAYAN_API_TOKEN``). Si la variable no esta definida la
escritura queda deshabilitada (403) salvo que ``POPAYAN_DEMO_OPEN=1``.
La base se toma de ``POPAYAN_DB_PATH``.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from datetime import datetime
from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError

from src.api.exports import DISCLAIMER, observations_csv, stations_geojson, tracks_geojson
from src.contracts import IngestionResult, Observation, ReviewStatus
from src.storage.db import DEFAULT_DB_PATH, Storage

app = FastAPI(
    title="Demo de localizacion multisensor - Popayan (DATOS SIMULADOS)",
    description=(
        "API de investigacion y simulacion. Todos los datos son simulados y los nodos son "
        "ficticios. Las alertas son informativas y requieren revision humana."
    ),
    version="1.0.0",
)

_storages: dict[str, Storage] = {}
_storage_lock = threading.Lock()
_pipeline_lock = threading.Lock()


def get_storage() -> Storage:
    path = os.environ.get("POPAYAN_DB_PATH") or str(DEFAULT_DB_PATH)
    with _storage_lock:
        if path not in _storages:
            _storages[path] = Storage(path)
        return _storages[path]


def require_write_access(x_api_token: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("POPAYAN_API_TOKEN", "")
    if not expected:
        if os.environ.get("POPAYAN_DEMO_OPEN") == "1":
            return
        raise HTTPException(
            status_code=403,
            detail="Escritura deshabilitada: defina POPAYAN_API_TOKEN (o POPAYAN_DEMO_OPEN=1 solo para demo local).",
        )
    if not x_api_token or not hmac.compare_digest(x_api_token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Token invalido o ausente (cabecera X-API-Token).")


# ----------------------------------------------------------------------------- lectura


@app.get("/health")
def health(storage: Storage = Depends(get_storage)) -> dict[str, Any]:
    return {"status": "ok", "is_simulated": True, "disclaimer": DISCLAIMER, "counts": storage.counts()}


@app.get("/stations")
def stations(storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in storage.list_stations()]


@app.get("/observations")
def observations(
    station_id: Optional[str] = None,
    sensor_type: Optional[str] = None,
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    storage: Storage = Depends(get_storage),
) -> list[dict[str, Any]]:
    rows = storage.list_observations(station_id, sensor_type, desde, hasta, limit)
    return [o.model_dump(mode="json") for o in rows]


def _track_view(track, decision) -> dict[str, Any]:
    out = track.model_dump(mode="json")
    out["state"] = decision.state.value if decision else None
    out["rule_id"] = decision.rule_id if decision else None
    out["reason"] = decision.reason if decision else None
    out["requires_human_review"] = decision.requires_human_review if decision else None
    return out


@app.get("/tracks")
def tracks(storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    latest = storage.latest_decisions()
    return [_track_view(t, latest.get(t.track_id)) for t in storage.list_tracks()]


@app.get("/tracks/{track_id}")
def track_detail(track_id: str, storage: Storage = Depends(get_storage)) -> dict[str, Any]:
    t = storage.get_track(track_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Track no encontrado.")
    decisions = storage.list_decisions(track_id)
    out = _track_view(t, decisions[-1] if decisions else None)
    out["decisions"] = [d.model_dump(mode="json") for d in decisions]
    return out


@app.get("/decisions")
def decisions(track_id: Optional[str] = None, storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in storage.list_decisions(track_id)]


@app.get("/alerts")
def alerts(review_status: Optional[ReviewStatus] = None, storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in storage.list_alerts(review_status.value if review_status else None)]


@app.get("/audit")
def audit(limit: Optional[int] = Query(default=None, ge=1, le=100000), storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in storage.list_audit(limit=limit)]


@app.get("/rejected")
def rejected(limit: Optional[int] = Query(default=None, ge=1, le=100000), storage: Storage = Depends(get_storage)) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in storage.list_rejected(limit)]


# -------------------------------------------------------------------------- exportacion


@app.get("/export/observations.csv")
def export_observations(storage: Storage = Depends(get_storage)) -> Response:
    return Response(
        content=observations_csv(storage.list_observations()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="observaciones_SIMULADAS.csv"'},
    )


@app.get("/export/tracks.geojson")
def export_tracks(storage: Storage = Depends(get_storage)) -> Response:
    data = tracks_geojson(storage.list_tracks(), storage.latest_decisions())
    return Response(content=json.dumps(data), media_type="application/geo+json")


@app.get("/export/stations.geojson")
def export_stations(storage: Storage = Depends(get_storage)) -> Response:
    return Response(content=json.dumps(stations_geojson(storage.list_stations())), media_type="application/geo+json")


# ----------------------------------------------------------------------------- escritura


class ReviewBody(BaseModel):
    status: ReviewStatus
    reviewer: str = Field(min_length=1, max_length=64)
    note: Optional[str] = Field(default=None, max_length=1000)


class DemoRunBody(BaseModel):
    scenario: str = Field(default="basico", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


@app.post("/alerts/{alert_id}/review", dependencies=[Depends(require_write_access)])
def review_alert(alert_id: str, body: ReviewBody, storage: Storage = Depends(get_storage)) -> dict[str, Any]:
    if body.status == ReviewStatus.PENDIENTE:
        raise HTTPException(status_code=422, detail="La revision debe ser 'confirmada' o 'descartada'.")
    try:
        alert = storage.review_alert(alert_id, body.status, body.reviewer, body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return alert.model_dump(mode="json")


def _get_pipeline():
    """Pipeline operativo si el modulo existe; ``None`` si no (solo se persiste)."""
    if getattr(app.state, "pipeline", None) is None:
        try:
            from src.decision_agents.pipeline import OperationalPipeline
        except ImportError:
            return None
        app.state.pipeline = OperationalPipeline()
    return app.state.pipeline


@app.post("/observations", status_code=201, dependencies=[Depends(require_write_access)])
def post_observation(payload: dict[str, Any] = Body(...), storage: Storage = Depends(get_storage)) -> dict[str, Any]:
    try:
        obs = Observation.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json(include_url=False, include_context=False)))
    storage.save_ingestion(IngestionResult(observation=obs))
    processed = False
    pipeline = _get_pipeline()
    if pipeline is not None:
        with _pipeline_lock:
            result = pipeline.process_batch([obs], now_utc=obs.timestamp_utc)
            storage.save_pipeline_result(result)
        processed = True
    return {"event_id": obs.event_id, "persisted": True, "pipeline_processed": processed,
            "is_simulated": obs.is_simulated}


@app.post("/demo/run", dependencies=[Depends(require_write_access)])
def demo_run(body: Optional[DemoRunBody] = None, storage: Storage = Depends(get_storage)) -> dict[str, Any]:
    from src.orchestration import runner

    body = body or DemoRunBody()
    app.state.pipeline = None  # el estado del pipeline de POST /observations se reinicia con la demo
    try:
        return runner.run_demo(body.scenario, body.seed, storage=storage, reset=True)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Escenario no valido: {exc}")
