# P3 — Demo de localización multisensor (Popayán) · DATOS SIMULADOS

Proyecto de **investigación y simulación**. Combina observaciones de sensores
**virtuales** (Remote ID de ejemplo, acústico, RF, óptico, radar) emitidas por un
simulador, las valida, las correlaciona en trayectorias, aplica reglas
deterministas y produce **alertas informativas que requieren revisión humana**.

> Todo dato es simulado y todos los nodos son ficticios. Nada de esto es una
> detección real ni demuestra el alcance de ningún equipo.

## Qué incluye

- Simulador de escenarios con nombre (`basico`, `sin_remote_id`, `duplicados`,
  `contradictorio`, `corroborado`, `perdida_senal`, `estacion_caida`,
  `malformados`, `sin_estacion_control`, `rangos_100m_10km`).
- Ingesta y validación, correlación, seguimiento, motor de estados explicable y auditoría.
- Persistencia SQLite, API REST (FastAPI) y dashboard (Streamlit + Folium).
- Exportación CSV y GeoJSON marcada como `DATOS SIMULADOS`.

## Instalación

Entorno recomendado (fuera de OneDrive): `C:\Users\sebas\.venvs\p3-popayan`, Python 3.11.

```bash
cd demo-localizacion-drones-popayan
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe -m pip install -r requirements.txt
```

## Comandos

```bash
PY=C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe
$PY app.py scenarios                              # lista de escenarios
$PY app.py demo --scenario basico --seed 42       # ejecuta y resume (DATOS SIMULADOS)
$PY app.py api --port 8000                        # API en http://127.0.0.1:8000/docs
$PY app.py dashboard                              # dashboard Streamlit
$PY -m pytest tests/storage tests/api tests/orchestration -q
```

### API

Lectura abierta: `/health`, `/stations`, `/observations` (filtros `station_id`,
`sensor_type`, `desde`, `hasta`, `limit`), `/tracks`, `/tracks/{id}`, `/decisions`,
`/alerts`, `/audit`, `/rejected`, `/export/observations.csv`,
`/export/tracks.geojson`, `/export/stations.geojson`.

Escritura y revisión (`POST /observations`, `POST /alerts/{id}/review`,
`POST /demo/run`) exigen la cabecera `X-API-Token` igual a la variable de entorno
`POPAYAN_API_TOKEN`. Si la variable no está definida la escritura devuelve 403,
salvo que se active explícitamente `POPAYAN_DEMO_OPEN=1` (solo para uso local).
La base se elige con `POPAYAN_DB_PATH` (por defecto `data/runtime/popayan_demo.sqlite`,
ignorada por git). No guarde tokens en el código ni en el repositorio.

### Dashboard

Banner permanente de datos simulados; mapa Folium con teselas públicas de
OpenStreetMap (© OpenStreetMap contributors) y capas separadas: estaciones civiles
ficticias, trayectorias observadas, posición reportada del dron, estación de control
reportada, punto de despegue reportado y, opcional y apagada por defecto, la
«verdad del simulador». Si no hay red, use la vista provisional sin teselas.
Los nodos institucionales abstractos se listan en un panel aparte, sin ubicación.
Las alertas se revisan a mano (confirmar/descartar + nota) y la revisión queda en la auditoría.

## Estructura

```
app.py                     punto de entrada (demo | api | dashboard | scenarios)
src/contracts/             contratos compartidos (coordinador)
src/simulation/            escenarios y estado verdadero (S3)
src/remote_id/, src/ingestion/   Remote ID de ejemplo, ingesta y validación (O2)
src/correlation/, tracking/, decision_agents/, audit/   fusión y decisiones (O3)
src/storage/db.py          Storage (SQLite)
src/stations/registry.py   registro de nodos ficticios
src/orchestration/runner.py run_demo (lotes por tiempo)
src/api/                   FastAPI y exportaciones
src/dashboard/app.py       Streamlit + Folium
tests/                     pruebas por módulo
```

## Límites y avisos

- Las cinco estaciones civiles tienen coordenadas **inventadas**; no son equipos ni sedes reales.
- Los nodos `INST-SIM-*` son **abstractos y no tienen coordenadas**; no representan
  instalaciones, equipos ni unidades reales y nunca se dibujan en el mapa ni en GeoJSON.
- **Simulado ≠ real**: todo dato del simulador lleva `is_simulated=true` y se rotula así
  en la interfaz, el CSV y el GeoJSON. El estado verdadero del escenario va en una tabla aparte.
- Las pruebas de 100 m a 10 km validan el **software**, no el alcance de ningún hardware.
- Audio no produce coordenadas; RSSI por sí solo no produce localización.
- Las posiciones de dron, estación de control y despegue son **reportadas y no verificadas**.
- Solo alertas informativas con revisión humana: el sistema no clasifica amenazas ni
  hostilidad, no sugiere acciones físicas, no deduce la identidad de ninguna persona,
  no ubica instalaciones y no intercepta ni interfiere señales.
