# P2 — Clasificador acústico `drone` / `no_drone`

Demo de investigación: clasifica ventanas de audio como `drone` o `no_drone` con features
log-mel/MFCC y un clasificador ligero (scikit-learn, CPU, sin torch). Exporta observaciones al
simulador de Popayán (P3) según `contracts/observation.schema.json`.

> **Límite fundamental:** la clasificación de audio **no da coordenadas, altura ni distancia**.
> Toda observación exportada lleva `latitude`, `longitude` y `altitude` = `null`; el esquema
> rechaza una observación acústica con coordenadas.

## Instalación (Windows, Python 3.11, entorno fuera de OneDrive)

```bash
python -m venv C:/Users/sebas/.venvs/p2-audio
C:/Users/sebas/.venvs/p2-audio/Scripts/python.exe -m pip install -r requirements.txt
```

Todos los comandos se ejecutan desde esta carpeta (`demo-deteccion-drones-audio/`). Abreviatura:
`PY=C:/Users/sebas/.venvs/p2-audio/Scripts/python.exe`.

## Comandos

```bash
# tests (deterministas, con audio SINTÉTICO)
$PY -m pytest -q

# entrenamiento con datos reales (DroneDetectionThesis, descargado por el kit en data/raw/)
$PY scripts/train.py --data-dir data/raw/DroneDetectionThesis/Data/Audio \
    --rule prefix --label-map config/label_map_dronedetectionthesis.json
$PY scripts/evaluate.py --notes docs/notas-dataset-DroneDetectionThesis.md
#   -> modelos/audio_clf.joblib, resultados/metricas.json, docs/reporte-metricas.md

# prueba de humo SIMULADA (audio sintético; cifras NO son rendimiento real)
$PY scripts/train.py --synthetic
$PY scripts/evaluate.py --results-dir resultados/simulado
#   -> modelos/SIMULADO_audio_clf.joblib, docs/reporte-metricas-SIMULADO.md

# predicción de un WAV (salida JSON determinista)
$PY scripts/predict.py --wav data/raw/DroneDetectionThesis/Data/Audio/DRONE_001.wav
# ... y exportación de observaciones JSONL para P3
$PY scripts/predict.py --wav ruta.wav --export-jsonl resultados/observaciones.jsonl \
    --station-id P2-ACUSTICA-01 --timestamp 2026-11-11T12:00:00Z [--per-window]

# API
$PY app.py --port 8002            # GET /health, POST /predict (multipart, campo "file")
curl -F "file=@ruta.wav" "http://127.0.0.1:8002/predict?station_id=P2-ACUSTICA-01&timestamp_utc=2026-11-11T12:00:00Z"
```

## Estructura

| Ruta | Contenido |
|---|---|
| `src/audio/io.py` | carga WAV → mono, remuestreo a 16 kHz (`resample_poly`), normalización |
| `src/audio/segment.py` | ventanas de 1 s con salto de 0,5 s |
| `src/audio/features.py` | `FeatureConfig` (dataclass); log-mel (40 bandas), MFCC (20) + deltas + estadísticos espectrales; media y desviación por ventana (136 features). Implementado con numpy/scipy |
| `src/audio/synthetic.py` | generador **SIMULADO** (zumbido armónico modulado vs. ruido ambiente) solo para tests |
| `src/models/classifier.py` | `AudioClassifier`: StandardScaler + regresión logística (`logreg`) o bosque aleatorio (`rf`); `fit`, `predict_proba`, `save`, `load`; versión = hash del modelo |
| `src/models/splits.py` | división train/val/test **por grabación** (estratificada por clase original, semilla fija) |
| `src/models/threshold.py` | umbral que maximiza F1 en validación |
| `src/models/metrics.py` | precisión, recall, F1, especificidad, matriz de confusión por ventana y por grabación |
| `src/dataset.py` | manifiesto: etiqueta leída del prefijo del archivo o de la carpeta + mapa explícito |
| `src/export/observations.py` | predicción → observaciones validadas con `jsonschema` → JSONL |
| `scripts/` | `train.py`, `evaluate.py`, `predict.py` |
| `app.py` | API FastAPI mínima |
| `config/label_map_dronedetectionthesis.json` | `DRONE→drone`, `HELICOPTER→no_drone`, `BACKGROUND→no_drone` |

Artefactos (ignorados por git): `modelos/`, `resultados/`, `data/raw/`, `data/interim/`.

## Exportación a P3 (contrato `observation.schema.json` v1.0.0)

Una línea JSONL por observación:

```json
{"event_id": "<uuid5 determinista>", "station_id": "P2-ACUSTICA-01", "sensor_type": "acoustic",
 "timestamp_utc": "2026-11-11T12:00:00Z", "data_origin": "replay", "is_simulated": false,
 "object_id": null, "classification": "drone", "classifier_score": 0.93,
 "latitude": null, "longitude": null, "altitude": null, "altitude_reference": null,
 "measurement_uncertainty": null, "sensor_quality": null,
 "raw_reference": "DRONE_001.wav|model=p2-audio-logreg-…|thr=0.44"}
```

- `data_origin = "replay"` para WAV de un dataset grabado; `"simulation"` (con `is_simulated=true`)
  para audio sintético (archivos `SIMULADO_*`, detectado automáticamente o forzado con `--data-origin`).
- `classification` = `drone` si `classifier_score ≥ umbral`, si no `no_drone`.
- Cada observación se valida contra el esquema antes de escribirse; si falla, no se exporta.
- `station_id` es configurable; P2 no asigna posición a la estación (eso lo hace P3 con sus
  estaciones ficticias).

## Resultados y límites

- Métricas reales: `docs/reporte-metricas.md` (dataset DroneDetectionThesis, 90 clips de 10 s).
- Prueba de humo sintética: `docs/reporte-metricas-SIMULADO.md` (**SIMULADO**, no es rendimiento).
- Dataset pequeño (30 clips por clase original): las métricas varían mucho según la división;
  ver el análisis de sensibilidad a la semilla en el reporte.
- El modelo no se ha probado en campo, con otros micrófonos, ni en Popayán. No estima distancia,
  rumbo ni altura, ni identifica modelo de dron u operador.
