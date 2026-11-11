# Reporte de pruebas

Fecha: 2026-11-11 (≈20:20 UTC). Equipo: Windows 11, Python 3.11.9. Pruebas ejecutadas por
`ingeniero-qa-devops` (`claude-haiku-5-5`) y repetidas por el coordinador (`claude-fable-5-2`).
Este documento lo redactó el coordinador a partir de las salidas reales.

Para ver la línea de resumen hay que anular el `-q` de los `pytest.ini`: `-o addopts="" -q`.

## Resultados por proyecto

| Proyecto | Comando (desde la raíz del proyecto) | Salida real | Duración |
|---|---|---|---|
| P1 UniFace | `C:/Users/<usuario>/.venvs/p1-uniface/Scripts/python.exe -m pytest -o addopts="" -q -rs` | `17 passed` | 6–20 s |
| P2 audio | `C:/Users/<usuario>/.venvs/p2-audio/Scripts/python.exe -m pytest -o addopts="" -q` | `26 passed, 1 warning` | ≈10 s |
| P3 Popayán | `C:/Users/<usuario>/.venvs/p3-popayan/Scripts/python.exe -m pytest -o addopts="" -q -rs` | `338 passed, 1 warning` (antes de generar las imágenes de Blender: `333 passed, 1 skipped`) | ≈5 min |
| P3 solo integración | `... -m pytest tests/integration -o addopts="" -q -rs` | `15 passed` | ≈5,5 min |

- Aviso (P2 y P3): deprecación de `httpx` dentro de `starlette.testclient`. No afecta al resultado.
- Pruebas saltadas: ninguna en la última ejecución. `tests/blender/test_blender_yolo.py` se saltaba
  mientras no hubo `blender.exe`; tras instalar Blender 4.4.3 y generar las imágenes, se ejecuta.
- Fallos: ninguno.

Desglose de P3: contratos e ingesta 189 · simulación 23 · Blender y validador YOLO 15 · fusión,
seguimiento, decisiones y auditoría 61 · almacenamiento, API y orquestación 35 · integración 15.

## Imágenes sintéticas de Blender

Comando: `"C:/Program Files/Blender Foundation/Blender 4.4/blender.exe" --background --python
blender/generate_scene.py -- --out data/synthetic/examples/blender --n 4 --seed 42`
(Blender 4.4.3, Cycles por CPU, 32 muestras, 640×480).

| Imagen | Caja etiquetada (px) | Dron medido en la imagen (px) | Desvío máximo |
|---|---|---|---|
| `drone_000.png` | (307,8 · 266,7 · 354,6 · 287,1) | (309 · 267 · 353 · 286) | 1,6 px |
| `drone_001.png` | (290,7 · 252,8 · 331,6 · 265,1) | (293 · 254 · 329 · 264) | 2,6 px |
| `drone_002.png` | (274,5 · 252,7 · 325,0 · 275,2) | (275 · 253 · 323 · 274) | 2,0 px |
| `drone_003.png` | (344,2 · 267,5 · 446,9 · 342,9) | (345 · 268 · 445 · 341) | 1,9 px |

La medición la hace `tests/blender/test_etiqueta_vs_pixeles.py` buscando el cuerpo naranja y las
piezas oscuras del dron; tolerancia de la prueba: 4 px por borde. Dos incidencias en la primera
ejecución, ya corregidas: el motor Workbench cerró Blender (fallo de compilación de shaders con el
controlador gráfico) y la ruta de salida relativa dejó los PNG fuera del proyecto.

## Escenarios obligatorios (P3, módulos reales, sin dobles, semilla 42, base temporal)

Archivo: `demo-localizacion-drones-popayan/tests/integration/test_escenarios_obligatorios.py`.

| # | Escenario | Escenario del simulador | Qué comprueba | Resultado |
|---|---|---|---|---|
| 1 | Observación válida | `basico` | algún track alcanza `DETECCION_POSIBLE`; 0 rechazados | aprobado |
| 2 | Pérdida de señal | `perdida_senal` | `SEGUIMIENTO_PERDIDO` con `reason` y `rule_id` | aprobado |
| 3 | Duplicados | `duplicados` | `duplicates > 0`; ningún `event_id` repetido | aprobado |
| 4 | Fuentes contradictorias | `contradictorio` | `REQUIERE_REVISION` con revisión humana | aprobado |
| 5 | Dos fuentes independientes consistentes | `corroborado` | `DETECCION_CORROBORADA` | aprobado |
| 6 | Datos obsoletos | `malformados` | rechazo `STALE`; tracks finales perdidos | aprobado |
| 7 | Dron sin estación de control conocida | `sin_estacion_control` | Remote ID aceptado sin ninguna `control_station` | aprobado |
| 8 | Punto de despegue sin controlador | `sin_estacion_control` | hay `takeoff_point`, no hay `control_station` | aprobado |
| 9 | Audio sin coordenadas | `basico` | ninguna observación acústica con posición; tracks solo acústicos sin puntos | aprobado |
| 10 | Estación caída | `estacion_caida` | `CIV-02` `offline`; rechazos `STATION_OFFLINE` | aprobado |
| 11 | Datos malformados | `malformados` | termina sin excepción; cada rechazo tiene código y motivo | aprobado |
| 12 | Simulado vs real | `basico` | todo `is_simulated`; el contrato rechaza `sensor` + `is_simulated=True` | aprobado |
| + | Nodos abstractos | `basico` | `INST-SIM-01/02` sin coordenadas | aprobado |
| + | Alertas | `basico` | todas `severity == "informativa"` | aprobado |
| + | Determinismo | `basico` ×2 | mismos `decision_id` y conteos | aprobado |

Nota sobre el escenario 9: la versión inicial de la prueba pasaba aunque no hubiera tracks solo
acústicos. El coordinador comprobó en la base real que `basico` produce 4 tracks de presencia
acústicos con 0 puntos y añadió la aserción de que la lista no esté vacía.

## Comprobaciones adicionales del coordinador

| Comprobación | Resultado |
|---|---|
| 10 escenarios con `run_demo` y recuento por estado | los 10 terminan sin excepción (tabla en `docs/estado_general.md`) |
| `python app.py demo --scenario basico --seed 42` | 2607 eventos, 165 duplicados, 0 rechazados, 11 tracks, 33 decisiones, 10 alertas |
| API como servidor real (`python app.py api --port 8011`) | `/health` 200; `/stations` 7 nodos con `INST-SIM` sin coordenadas; `stations.geojson` con 5 entidades; `tracks.geojson` con `disclaimer`; `POST /demo/run` sin token → 401; `POST /observations` acústica con coordenadas → 422 |
| Dashboard en navegador (`python app.py dashboard`) | carga en `127.0.0.1:8501`; banner de datos simulados; mapa con teselas de OpenStreetMap; 6 pestañas; formulario de revisión visible; sin errores de consola |
| P2 `scripts/predict.py` con audio real | `DRONE_005` → probabilidades ≈0,99; `HELICOPTER_007` y `BACKGROUND_011` → ≈0 |
| P1 `scripts/demo_cli.py` | 1 rostro detectado, `desconocido` con galería vacía, CSV escrito |
| LFW | SHA256 de `lfw-funneled.tgz` coincide con el oficial |

## Lint (informativo, sin corregir)

`ruff check . --statistics` en P3: 277 avisos, casi todos de estilo
(`UP045` 164 — `Optional[X]` en lugar de `X | None`; `UP017` 23; `B008` 16 — `Depends` de FastAPI
en argumentos por defecto; `UP035` 10; `I001` 9 — orden de imports).

## Integración continua

`.github/workflows/p1-uniface.yml`, `p2-audio.yml`, `p3-popayan.yml`: `PREPARADO_NO_EJECUTADO`.
El YAML carga correctamente, pero nunca han corrido en GitHub (no hay remoto ni `gh`).

## No probado

- Motor Workbench de Blender (falla en este equipo; se usa Cycles por CPU).
- Workflows en GitHub.
- Registrar la revisión de una alerta y descargar CSV/GeoJSON desde el dashboard con el ratón
  (la revisión y las exportaciones sí están cubiertas por pruebas de la API).
- Subir una foto en la interfaz Streamlit de P1 (solo se comprobó que arranca).
- API de P2 como servidor en vivo (probada con `TestClient`).
- Instalación limpia desde cero en otra máquina.
