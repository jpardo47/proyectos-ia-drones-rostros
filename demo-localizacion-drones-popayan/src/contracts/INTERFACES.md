# Interfaces entre módulos — Proyecto 3

Propietario: coordinador (Fable). Estas firmas son **obligatorias**: cada dueño
implementa exactamente estas rutas y nombres para que los módulos escritos en
paralelo encajen. Todo se importa como paquete `src.*` con la raíz del proyecto
(`demo-localizacion-drones-popayan/`) como directorio de trabajo.

Tipos: `from src.contracts import ...` (ver `observation.py`, `domain.py`,
`remote_id_wire.py`). Nadie más edita `src/contracts/`, `requirements.txt`,
`pytest.ini` ni `data/stations/estaciones_ficticias.json`.

## Flujo

```
simulation (S3) ──RawEvent──▶ ingestion+validator (O2) ──Observation──▶ pipeline (O3)
       │ truth (separado)                                                   │
       ▼                                                                    ▼
   storage (S2) ◀── Station / Observation / Track / Decision / Alert / Audit ┘
       ▼
   api + dashboard (S2)          blender (S3): imágenes sintéticas + etiquetas YOLO
```

## S3 — `src/simulation/` (ingeniero-simulacion-blender)

```python
# src/simulation/scenario.py
class ScenarioConfig(BaseModel):           # campos mínimos; puede tener más con valores por defecto
    name: str
    seed: int = 42
    duration_s: int = 300
    step_s: float = 1.0
    start_utc: datetime                     # tz-aware; por defecto fijo -> determinista

def list_scenarios() -> list[str]: ...
def get_scenario(name: str, seed: int = 42) -> ScenarioConfig: ...
def run_scenario(config: ScenarioConfig) -> ScenarioResult: ...   # determinista por seed
```

Escenarios con nombre obligatorios: `basico`, `sin_remote_id`, `duplicados`,
`contradictorio`, `corroborado`, `perdida_senal`, `estacion_caida`, `malformados`,
`sin_estacion_control`, `rangos_100m_10km`.

`ScenarioResult.raw_events` contiene `RawEvent`:
- `kind="remote_id"`: `payload` = `RemoteIdWireMessage(...).model_dump(mode="json")`
  (o un dict roto a propósito en `malformados`).
- `kind="observation"`: `payload` = `Observation(...).model_dump(mode="json")`
  para sensores acústico / rf / óptico / radar virtuales. Acústico: **sin** coordenadas.
- `event_id` de observaciones y `message_id` de Remote ID: deterministas
  (derivados de seed + estación + paso), nunca `uuid4()` aleatorio.

`truth` nunca se mezcla con `raw_events`.

## O2 — `src/remote_id/` y `src/ingestion/` (ingeniero-remote-id)

```python
# src/remote_id/parser.py
class RemoteIdParseError(ValueError):       # .reason_code: str, .reason: str
def parse_remote_id(raw: dict | str | bytes) -> RemoteIdWireMessage: ...
# src/remote_id/validation.py
def validate_remote_id(msg: RemoteIdWireMessage, received_at_utc: datetime) -> list[str]: ...  # errores; [] = válido
# src/remote_id/convert.py
def to_ingestion_result(msg, station_id: str, received_at_utc: datetime) -> IngestionResult: ...

# src/ingestion/agent_ingestion.py
class IngestionAgent:
    name = "agent_ingestion"; version: str
    def ingest(self, event: RawEvent) -> IngestionResult | RejectedInput: ...
# src/ingestion/agent_validator.py
class ValidatorAgent:
    name = "agent_validator"; version: str
    def __init__(self, known_station_ids: set[str] | None = None, max_age_s: float = 120.0, max_future_s: float = 5.0): ...
    def validate(self, result: IngestionResult, now_utc: datetime) -> IngestionResult | RejectedInput: ...
# src/ingestion/adapters.py  -> clase abstracta ReceiverAdapter (recepción autorizada) + ReplayFileAdapter
```

## O3 — `src/correlation/`, `src/tracking/`, `src/decision_agents/`, `src/audit/` (ingeniero-fusion-decisiones)

```python
# src/decision_agents/pipeline.py
ENGINE_VERSION: str
class PipelineConfig(BaseModel): ...        # umbrales con valores por defecto documentados
class OperationalPipeline:
    def __init__(self, config: PipelineConfig | None = None): ...
    def process_batch(
        self,
        observations: Sequence[Observation],
        now_utc: datetime,
        station_status: Mapping[str, StationStatus] | None = None,
    ) -> PipelineResult: ...
    def current_tracks(self) -> list[Track]: ...
    def current_states(self) -> dict[str, DetectionState]: ...   # track_id -> estado
```

Con estado entre lotes, determinista, sin reloj de pared (`now_utc` inyectado),
IDs deterministas. Agentes internos: `agent_correlator`, `agent_tracker`,
`agent_quality`, `agent_evidence`, `agent_alerts`, `agent_audit`.

## S2 — `src/storage/`, `src/stations/`, `src/api/`, `src/dashboard/`, `app.py`, `src/orchestration/` (ingeniero-api-dashboard)

```python
# src/storage/db.py
class Storage:
    def __init__(self, db_path: str | Path = "data/runtime/popayan_demo.sqlite"): ...
    def init_schema(self) -> None: ...
    def upsert_stations(self, stations: Iterable[Station]) -> None: ...
    def save_ingestion(self, result: IngestionResult) -> None: ...        # observación + related_locations
    def save_rejected(self, rejected: RejectedInput) -> None: ...
    def save_pipeline_result(self, result: PipelineResult) -> None: ...
    def save_truth(self, scenario_id: str, truth: Iterable[TruthState]) -> None: ...   # tabla aparte, marcada SIMULADO
    def review_alert(self, alert_id: str, status: ReviewStatus, reviewer: str, note: str | None) -> Alert: ...
    # + consultas list_* que usan api y dashboard

# src/orchestration/runner.py
def run_demo(scenario: str = "basico", seed: int = 42, db_path=..., reset: bool = True) -> dict: ...
#   simulation.run_scenario -> IngestionAgent -> ValidatorAgent -> OperationalPipeline -> Storage
#   procesa en lotes por paso de tiempo; devuelve un resumen (conteos por estado, rechazados, alertas)

# src/api/main.py -> app = FastAPI(...)   | uvicorn src.api.main:app
# src/dashboard/app.py                    | streamlit run src/dashboard/app.py
# app.py:  python app.py demo|api|dashboard [--scenario ... --seed ...]
```

## Reglas comunes

- Python 3.11, Pydantic v2. Entorno: `C:\Users\sebas\.venvs\p3-popayan` (fuera de OneDrive).
  Ejecutable: `C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe`. No ejecutar `pip install`.
- Tests propios en `tests/<tu_modulo>/` (p. ej. `tests/remote_id/`), deterministas, sin red.
- Texto visible al usuario en español. Todo dato simulado se etiqueta SIMULADO.
- Prohibido: clasificar amenazas/hostilidad, ordenar acciones, deducir identidad de personas,
  ubicaciones reales de instalaciones militares, interceptar o interferir señales.
- No hacer `git commit` ni `git add`: los commits los hace el coordinador.
