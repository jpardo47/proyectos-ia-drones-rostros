# Adaptador de recepción e ingesta Remote ID (P3)

Propietario: `ingeniero-remote-id` (O2). Código: `src/remote_id/`, `src/ingestion/`.
Estado: **IMPLEMENTADO_Y_PROBADO** para el formato de ejemplo y la reproducción de
archivos; **no existe** ningún adaptador de recepción física.

## 1. Qué es y qué no es

- El formato `rid-demo-1` (`src/contracts/remote_id_wire.py`) es **JSON de
  demostración** que agrupa campos al estilo de las familias de mensajes de
  ASTM F3411 / OpenDroneID (Basic ID, Location/Vector, System, Operator ID).
- **No** es una implementación binaria de ASTM F3411 ni de OpenDroneID, **no**
  decodifica tramas Bluetooth/Wi-Fi y **no** promete compatibilidad con ningún
  equipo, aplicación o receptor real.
- Todos los mensajes de `data/examples/remote_id/` son **ficticios**, con
  coordenadas inventadas alrededor del punto público de referencia
  (Parque Caldas, 2.4419, -76.6063). Ninguna coordenada corresponde a
  instalaciones reales.

## 2. Limitaciones de Remote ID que el sistema asume

- **Puede faltar.** Muchos drones no emiten Remote ID, o lo tienen desactivado o
  fuera de alcance. La ausencia de Remote ID no prueba la ausencia de un dron.
- **Puede ser inexacto o falso.** Todas las posiciones son *auto-reportadas* por el
  emisor y no están verificadas: la ingesta añade el aviso
  "ubicaciones auto-reportadas por Remote ID; no verificadas".
- **Tres ubicaciones distintas**, nunca intercambiables: dron (`Observation`),
  estación de control (`related_locations`, rol `control_station`) y punto de
  despegue (rol `takeoff_point`). Si alguna falta **no se rellena ni se deduce**:
  se añade un aviso (p. ej. "estación de control no reportada"). Un punto de
  despegue nunca se promueve a estación de control.
- `operator_id` es un dato administrativo: **no se copia** a la observación ni se
  usa para deducir la identidad de ninguna persona.
- La precisión de OpenDroneID es una cota de ~95 %; se usa como
  `measurement_uncertainty` (1-sigma), lo que sobreestima la incertidumbre (conservador).

## 3. Flujo

```
RawEvent ──▶ IngestionAgent.ingest ──▶ ValidatorAgent.validate ──▶ Observation (pipeline)
                │ remote_id: parse_remote_id → validate_remote_id → to_ingestion_result
                │ observation: contrato Observation (tipado estricto) + reglas explícitas
                └─▶ RejectedInput(stage="ingestion")      └─▶ RejectedInput(stage="validation")
```

Ninguno de los dos agentes lanza excepciones ante entrada malformada: todo fallo se
devuelve como `RejectedInput` con `reason_code` estable y `reason` en español.
Ambos son deterministas: no leen el reloj del sistema (`received_at_utc` y
`now_utc` se inyectan) y no usan red.

### Reglas de altitud (`to_ingestion_result`)

Orden de preferencia: `altitude_geodetic_m` (`wgs84`) → `altitude_pressure_m`
(`msl`) → `height_agl_m` (`agl` o `takeoff` según `height_reference`). Sin ninguna,
la observación va sin altitud y con aviso.

### Tolerancias por defecto (`RemoteIdLimits`, `ValidatorAgent`)

| Parámetro | Defecto | Uso |
|---|---|---|
| `max_age_s` | 120 s | `STALE` si el mensaje es más viejo |
| `max_future_s` | 5 s | `FUTURE_TIMESTAMP` si está fechado más adelante |
| altitud geodésica/barométrica | [-500, 10000] m | `OUT_OF_RANGE` |
| altura sobre terreno/despegue | [-100, 3000] m | `OUT_OF_RANGE` |
| velocidad | [0, 100] m/s | `OUT_OF_RANGE` |
| rumbo | [0, 360] ° | `OUT_OF_RANGE` |
| precisión | [0, 10000] m (aviso > 1000 m) | `OUT_OF_RANGE` |
| identificadores | ≤ 128 caracteres, no vacíos | `INVALID_FIELD` |

Otras reglas: posición (0, 0) → `POSITION_SENTINEL` (en OpenDroneID es "sin dato");
`height_agl_m` sin `height_reference` → `INCOHERENT_FIELDS`; timestamp sin zona →
`TIMESTAMP_NO_TZ`; acústico con coordenadas → `ACOUSTIC_WITH_POSITION`;
`data_origin`/`is_simulated` incoherentes → `SIMULATION_FLAG_MISMATCH`;
estación fuera del catálogo → `UNKNOWN_STATION` (solo `ValidatorAgent`).

### Simulado frente a real

- `is_simulated=true` → `data_origin="simulation"`, siempre.
- `is_simulated=false` → el origen que configure el agente
  (`IngestionAgent(real_data_origin=...)`: `replay` por defecto, `sensor` o `manual`).
  Nunca `simulation`.
- `IngestionAgent(expect_simulated=True)` rechaza cualquier mensaje que se declare no
  simulado (y viceversa): un dato del simulador no puede pasar por real.

## 4. Especificación de `ReceiverAdapter`

`src/ingestion/adapters.py` define una clase **abstracta** y nada más:

```python
class ReceiverAdapter(ABC):
    def __init__(self, authorization: ReceptionAuthorization): ...  # obligatoria
    def events(self) -> Iterator[RawEvent]: ...                     # abstracto
    def describe(self) -> dict: ...                                 # abstracto (auditoría)
    def close(self) -> None: ...                                    # opcional
```

Una implementación concreta (que **no** forma parte de esta demo) debería:

1. Entregar `RawEvent(kind="remote_id", station_id, received_at_utc con zona, payload)`,
   con el `payload` en formato `rid-demo-1` y sin alterar los valores recibidos.
2. Marcar `is_simulated=false` solo para recepciones reales y documentar el origen.
3. Exponer en `describe()` el tipo de receptor, el alcance y la referencia de autorización.

### Requisitos de autorización

- Se exige una `ReceptionAuthorization` (referencia de permiso, entidad responsable,
  alcance y vigencia) al construir cualquier adaptador; sin referencia, se lanza
  `ValueError`. Es una constancia para auditoría, no un control de seguridad.
- Solo pueden recibirse emisiones de **difusión pública destinadas a ser recibidas**
  (como el broadcast de Remote ID), en el lugar y periodo autorizados y conforme a la
  normativa aplicable (en Colombia, la autoridad aeronáutica y la de espectro).
- **Prohibido:** interceptar comunicaciones privadas (enlaces de control o vídeo),
  transmitir, interferir o suplantar señales, e intentar identificar a personas.

## 5. `ReplayFileAdapter`

Reproduce archivos JSONL locales (sin red ni hardware). Cada línea es un sobre:

```json
{"kind": "remote_id", "station_id": "CIV-01", "received_at_utc": "2026-01-15T15:00:00.500Z", "payload": {...}}
```

Las líneas vacías o que empiezan por `#` se ignoran. Las líneas que no forman un
`RawEvent` (JSON roto, sobre incompleto, > 64 KiB) no se descartan en silencio: quedan
en `adapter.rejected` como `RejectedInput` con `raw_reference="<archivo>:<línea>"`.

Archivos de ejemplo: `data/examples/remote_id/validos.jsonl` (8 eventos aceptados,
incluido uno de reproducción no simulada) e `invalidos.jsonl` (14 casos rechazados,
cada uno con el motivo esperado en su identificador).

## 6. Pruebas

```bash
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe -m pytest tests/remote_id tests/ingestion
```
