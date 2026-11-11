# Simulación multisensor (P3) — DATOS SIMULADOS

Todo lo que produce `src/simulation/` es **sintético**: `data_origin="simulation"`, `is_simulated=true`.
No hay sensores, datasets ni equipos reales. Las pruebas de 100 m a 10 km demuestran **el software**,
no el alcance de ningún hardware.

## Cómo reproducir

```bash
cd demo-localizacion-drones-popayan
PY=~/.venvs/p3-popayan/Scripts/python.exe
$PY -m src.simulation.cli --list
$PY -m src.simulation.cli --scenario basico --seed 42 --out data/synthetic/examples/basico.json
$PY -m pytest tests/simulation tests/blender
```

API: `from src.simulation.scenario import list_scenarios, get_scenario, run_scenario`.
Misma `seed` + misma configuración => resultado idéntico (`random.Random(seed)`, `start_utc` fijo
`2026-03-15T14:00:00Z`, IDs `rid-<seed>-<estación>-d<n>-<paso>` / `obs-<seed>-<estación>-<sensor>-<paso>-<n>`; sin `uuid4` ni reloj).
El estado verdadero (`ScenarioResult.truth`) está separado de lo observado (`raw_events`, ordenados por `received_at_utc`).

## Escenarios

| Nombre | Qué ejercita |
|---|---|
| `basico` | 3 drones: Remote ID completo (operador + despegue), despegue sin operador, y uno sin Remote ID |
| `sin_remote_id` | Ningún Remote ID: solo acústico (sin posición), RF (sin posición), óptico y radar (con posición) |
| `duplicados` | Mismo `message_id`/`event_id` reentregado y recibido por varias estaciones |
| `contradictorio` | Mismo `object_id` al mismo tiempo, posiciones a ~4,3 km (CIV-04 desplaza su Remote ID) |
| `corroborado` | Remote ID + óptico (CIV-02) + radar abstracto (INST-SIM-02), independientes y consistentes |
| `perdida_senal` | DRN-001 deja de ser observado a t=150 s; DRN-002 sigue |
| `estacion_caida` | CIV-02 pasa a `offline` a t=150 s y deja de emitir (`ScenarioResult.stations`) |
| `malformados` | Tráfico normal + 28 payloads rotos a propósito (campos faltantes, lat=999, timestamp sin zona o futuro, tipos erróneos, acústico con coordenadas, `is_simulated` incoherente) |
| `sin_estacion_control` | Remote ID sin operador; con y sin punto de despegue (desconocido, nunca deducido) |
| `rangos_100m_10km` | 6 drones estacionarios a 100 m, 500 m, 1, 3, 5 y 10 km de CIV-02 (alcances hipotéticos x8) |

Algunos payloads de `malformados` (lat=999, timestamp sin zona/futuro en Remote ID) pasan el modelo
permisivo `RemoteIdWireMessage` y deben ser rechazados por `src/remote_id`/validador; el resto falla ya en el contrato.

## Modelo de sensores (parámetros HIPOTÉTICOS)

Estaciones `CIV-*` (coordenadas ficticias): `p = p_max · exp(-(d/R)^k)` con `d` en 3D.

| Sensor | p_max | R (m) | k | Cadencia | Salida |
|---|---|---|---|---|---|
| remote_id | 0,95 | 4000 | 3 | 2 s | mensaje `rid-demo-1` con posición (GNSS σ=3 m) |
| acoustic | 0,90 | 1200 | 2 | 2 s | `classification="drone"`, `classifier_score`; **sin** lat/lon/alt |
| rf | 0,90 | 2500 | 2,5 | 3 s | detección **sin** posición |
| optical | 0,85 | 1500 | 3 | 3 s | posición, σ = 10 m + 0,01·d |
| radar | 0,90 | 6000 | 3 | 2 s | posición, σ = 15 m + 0,004·d |

Nodos `INST-SIM-01/02`: **sin coordenadas**; fuentes lógicas con probabilidad de recepción configurable
(`inst_rx_prob`, 0,8 por defecto) independiente de la distancia; el radar abstracto usa σ fija de 30 m.
Latencias de entrega 0,05–0,9 s, terreno hipotético plano a 1738 m. `range_scale` (solo en `rangos_100m_10km`,
x8) amplía los alcances para que el software reciba reportes a 10 km.

## Blender (imágenes sintéticas)

`blender/generate_scene.py` genera escena abstracta (terreno, bloques tipo edificio, cielo, dron genérico
de primitivas), render 640x480, `drone_NNN.png` + `drone_NNN.txt` (YOLO `0 cx cy w h`) y
`manifest.json`, proyectando los vértices del dron a la cámara con `world_to_camera_view`:

```bash
"C:/Program Files/Blender Foundation/Blender 4.4/blender.exe" --background --python blender/generate_scene.py -- --out data/synthetic/examples/blender --n 4 --seed 42
python -m src.simulation.yolo_validator data/synthetic/examples/blender
python -m pytest tests/blender
```

Motor de render: **Cycles por CPU** (`--engine CYCLES`, valor por defecto; `--samples 32`). Con
`--engine BLENDER_WORKBENCH` el render es más rápido, pero en el equipo de desarrollo (Blender 4.4.3,
Windows 11) sus shaders no compilan en modo `--background` y Blender se cierra con
`EXCEPTION_ACCESS_VIOLATION`.

Ejecutado el 2026-11-11: 4 imágenes (≈1–3 s cada una) en `data/synthetic/examples/blender/`.
`tests/blender/test_etiqueta_vs_pixeles.py` localiza el dron en cada imagen por su color y comprueba
que la caja etiquetada lo encierra de forma ajustada; desvío máximo medido: 2,6 px.

No representa instalaciones reales ni militares ni incluye modelos de armas.

## Límites

- No demuestra alcance real de ningún sensor; los parámetros son inventados para ejercitar el software.
- El audio no produce coordenadas; RF no produce localización.
- Las imágenes sintéticas de Blender no sustituyen datos reales para entrenar un detector.
