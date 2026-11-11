"""Ejecutor de la demo por lotes de tiempo. Todos los datos son SIMULADOS.

``simulation.run_scenario`` -> ``IngestionAgent`` -> ``ValidatorAgent`` ->
``OperationalPipeline`` -> ``Storage``. Las dependencias de otros modulos se
importan de forma perezosa y pueden inyectarse (para pruebas con dobles).
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from src.contracts import DetectionState, RejectedInput, ScenarioResult
from src.stations.registry import StationRegistry
from src.storage.db import DEFAULT_DB_PATH, Storage

DEFAULT_EXPIRY_S = 120.0
MAX_FLUSH_BATCHES = 600


def _missing(module: str, detail: Exception) -> ImportError:
    return ImportError(
        f"No se pudo importar el modulo '{module}' ({detail}). "
        "Ese modulo lo escribe otro equipo; verifique que exista con la firma de "
        "src/contracts/INTERFACES.md o inyecte un doble en run_demo()."
    )


def _default_simulate(scenario: str, seed: int) -> ScenarioResult:
    try:
        from src.simulation.scenario import get_scenario, run_scenario
    except ImportError as exc:
        raise _missing("src.simulation.scenario", exc) from exc
    return run_scenario(get_scenario(scenario, seed))


def _expiry_seconds(pipeline: Any) -> float:
    """Tiempo tras el cual el motor puede declarar una perdida (lee su configuracion si puede)."""
    config = getattr(pipeline, "config", None) or getattr(pipeline, "_config", None)
    values: list[float] = []
    if config is not None:
        names = getattr(type(config), "model_fields", None) or getattr(config, "__dict__", {})
        for name in names:
            low = name.lower()
            if any(k in low for k in ("lost", "timeout", "expire", "expiry", "stale", "max_gap")):
                v = getattr(config, name, None)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    values.append(float(v))
    return max(values) if values else DEFAULT_EXPIRY_S


def _batch_index(event_time: datetime, start: datetime, batch_s: float) -> int:
    return max(0, int(math.floor((event_time - start).total_seconds() / batch_s)))


def run_demo(
    scenario: str = "basico",
    seed: int = 42,
    db_path: str | Path = DEFAULT_DB_PATH,
    reset: bool = True,
    batch_seconds: float = 5.0,
    *,
    simulate: Optional[Callable[[str, int], ScenarioResult]] = None,
    ingestion_agent: Any = None,
    validator_agent: Any = None,
    pipeline: Any = None,
    storage: Optional[Storage] = None,
    flush_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Ejecuta un escenario completo y devuelve el resumen (SIMULADO)."""
    if batch_seconds <= 0:
        raise ValueError("batch_seconds debe ser > 0")

    result = (simulate or _default_simulate)(scenario, seed)

    if ingestion_agent is None:
        try:
            from src.ingestion.agent_ingestion import IngestionAgent
        except ImportError as exc:
            raise _missing("src.ingestion.agent_ingestion", exc) from exc
        ingestion_agent = IngestionAgent()
    registry = StationRegistry(result.stations)
    if validator_agent is None:
        try:
            from src.ingestion.agent_validator import ValidatorAgent
        except ImportError as exc:
            raise _missing("src.ingestion.agent_validator", exc) from exc
        validator_agent = ValidatorAgent(known_station_ids=set(registry.status_map()))
    if pipeline is None:
        try:
            from src.decision_agents.pipeline import OperationalPipeline
        except ImportError as exc:
            raise _missing("src.decision_agents.pipeline", exc) from exc
        pipeline = OperationalPipeline()

    store = storage if storage is not None else Storage(db_path)
    owns_store = storage is None
    try:
        if reset:
            store.reset()
        registry.sync(store)
        store.save_truth(result.scenario_id, result.truth)

        rejected_by_code: Counter[str] = Counter()
        duplicates = 0
        accepted_pipeline = 0
        valid_observations = 0
        alerts_seen: set[str] = set()
        decisions_seen: set[str] = set()

        def _reject(r: RejectedInput) -> None:
            store.save_rejected(r)
            rejected_by_code[r.reason_code] += 1

        events = sorted(result.raw_events, key=lambda e: e.received_at_utc)
        batches: dict[int, list] = {}
        for ev in events:
            batches.setdefault(_batch_index(ev.received_at_utc, result.start_utc, batch_seconds), []).append(ev)
        last_idx = max(batches) if batches else -1
        expiry = flush_seconds if flush_seconds is not None else _expiry_seconds(pipeline)
        flush_batches = min(MAX_FLUSH_BATCHES, int(math.ceil(expiry * 1.5 / batch_seconds)) + 2)
        total_batches = last_idx + 1 + flush_batches

        for idx in range(total_batches):
            batch_end = result.start_utc + timedelta(seconds=(idx + 1) * batch_seconds)
            valid = []
            for ev in batches.get(idx, []):
                ingested = ingestion_agent.ingest(ev)
                if isinstance(ingested, RejectedInput):
                    _reject(ingested)
                    continue
                checked = validator_agent.validate(ingested, now_utc=batch_end)
                if isinstance(checked, RejectedInput):
                    _reject(checked)
                    continue
                store.save_ingestion(checked)
                valid.append(checked.observation)
            valid_observations += len(valid)

            out = pipeline.process_batch(valid, now_utc=batch_end, station_status=registry.status_map())
            for r in out.rejected:
                _reject(r)
            duplicates += len(out.duplicates_dropped)
            accepted_pipeline += len(out.accepted)
            alerts_seen.update(a.alert_id for a in out.alerts)
            decisions_seen.update(d.decision_id for d in out.decisions)
            store.save_pipeline_result(out)

        tracks = store.list_tracks()
        latest = store.latest_decisions()
        by_state: Counter[str] = Counter()
        for t in tracks:
            d = latest.get(t.track_id)
            state = d.state.value if d else (
                DetectionState.SEGUIMIENTO_PERDIDO.value if t.is_lost else DetectionState.SIN_OBSERVACION.value
            )
            by_state[state] += 1

        summary: dict[str, Any] = {
            "titulo": "DATOS SIMULADOS - demostracion de investigacion, no son detecciones reales",
            "scenario": result.scenario_id,
            "seed": result.seed,
            "descripcion": result.description,
            "events": len(result.raw_events),
            "observaciones_validas": valid_observations,
            "accepted": accepted_pipeline,
            "rejected": sum(rejected_by_code.values()),
            "rejected_by_code": dict(sorted(rejected_by_code.items())),
            "duplicates": duplicates,
            "tracks": len(tracks),
            "tracks_by_state": dict(sorted(by_state.items())),
            "decisions": len(decisions_seen),
            "alerts": len(alerts_seen),
            "batches": total_batches,
            "batch_seconds": batch_seconds,
            "db_path": store.db_path,
            "is_simulated": True,
        }
        store.save_run(summary["scenario"], summary["seed"], summary)
        return summary
    finally:
        if owns_store:
            store.close()
