# P1 — Demo de reconocimiento facial con UniFace

Demo de visión por computador (investigación): detecta rostros, calcula embeddings y los compara
por similitud coseno contra una galería de personas **con consentimiento**. Si la similitud no supera
el umbral, o la galería está vacía, el resultado es `desconocido`. Usa la librería
[UniFace](https://github.com/yakhyo/uniface) 4.3.0 (ONNX Runtime, CPU): detector **RetinaFace**
(`MNET_V2`) y embeddings **ArcFace** (`MNET`, 512-D).

## Privacidad y uso responsable

- Usar **solo fotografías autorizadas** o datasets públicos de investigación (p. ej. LFW).
- No subir a git fotos personales, galerías (`datasets/galeria/`), embeddings (`*.npz`), pesos ni resultados.
- La app Streamlit no guarda las fotos subidas. Una galería de embeddings es dato biométrico: trátese como tal.
- Los resultados no son una identificación fiable ni deben usarse para decisiones sobre personas.
- Este proyecto no se relaciona con identificar personas que operan drones.

## Instalación (Windows, Python 3.11)

```bash
python -m venv C:/Users/<usuario>/.venvs/p1-uniface
C:/Users/<usuario>/.venvs/p1-uniface/Scripts/python.exe -m pip install -r requirements.txt
```

No requiere GPU ni torch. UniFace descarga los pesos preentrenados la primera vez que se usan; el
proyecto los guarda en `modelos/` (variable `UNIFACE_CACHE_DIR`, fijada en `src/paths.py`):
`retinaface_mnet_v2.onnx` (~12 MB) y `arcface_mnet.onnx` (~13 MB). Nota: `uniface` instala también
`opencv-python`; coexiste con `opencv-python-headless` sin problemas en las pruebas realizadas.

## Demo reproducible

```bash
PY=C:/Users/<usuario>/.venvs/p1-uniface/Scripts/python.exe   # desde la raíz de este proyecto

# 1) Sin argumentos: imagen de muestra de dominio público (skimage.data.astronaut, NASA)
$PY scripts/demo_cli.py --out resultados/demo.csv

# 2) Con tu propia foto autorizada y galería datasets/galeria/<nombre>/*.jpg
$PY scripts/demo_cli.py --image mi_foto.jpg --gallery datasets/galeria --threshold 0.4 --out resultados/demo.csv

# 3) Interfaz web
$PY -m streamlit run app.py
```

Para ver una coincidencia con la muestra: crear `datasets/galeria/astronauta/1.jpg` copiando
`datasets/muestras/astronaut_nasa.jpg` y repetir el paso 1 (resultado esperado: `astronauta`, similitud ≈ 1.0).
Con la galería vacía el resultado es `desconocido`.

CSV (`src/export.py`): `imagen, indice_rostro, x1, y1, x2, y2, puntuacion_deteccion, identidad, similitud, umbral, fecha_utc`.

## Estructura

```
app.py                  interfaz Streamlit (subir foto, cajas, tabla, CSV, umbral, avisos)
src/detector.py         detección: cajas, puntuación, 5 puntos clave (uniface.RetinaFace)
src/embedder.py         alineación + embedding L2-normalizado (uniface.ArcFace)
src/gallery.py          alta desde carpetas, guardado/carga .npz + .json
src/matcher.py          similitud coseno, umbral, "desconocido"
src/pipeline.py         imagen -> lista de resultados; dibujo de cajas
src/export.py           CSV
scripts/demo_cli.py     demo por línea de comandos
scripts/eval_lfw_pairs.py  evaluación acotada con pares de LFW
tests/                  pytest (unitarias sin pesos; integración marcada @pytest.mark.model)
modelos/ datasets/ resultados/ data/raw/   pesos, galería/muestras, salidas, datasets (fuera de git)
```

## Pruebas

```bash
$PY -m pytest -q                 # todo (las pruebas `model` se saltan si no hay pesos ni red)
$PY -m pytest -q -m "not model"  # solo unitarias, sin pesos
```

## Evaluación con LFW

`scripts/eval_lfw_pairs.py` evalúa 200 pares de `data/raw/lfw/pairsDevTest.txt` (100 positivos + 100
negativos, los primeros de cada bloque) y escribe `resultados/eval_lfw.json`. Resultado real de la
ejecución en esta máquina: ver `resultados/eval_lfw.json` (exactitud 0.975 al umbral 0.4; mejor umbral
en muestra ≈ 0.33). Es una evaluación **acotada** con pocos pares y poca diversidad de identidades
(los pares están ordenados alfabéticamente); no es el protocolo completo de 10 particiones de LFW.

## Límites

- Pesos ligeros (MobileNet): menos precisos que modelos grandes; sensibles a pose, oclusión, iluminación y baja resolución.
- Umbral por defecto 0.4 (coseno) es un punto de partida; debe calibrarse con datos propios.
- En la galería se usa el rostro más grande de cada foto; en la imagen consultada se procesan todos los rostros.
- Sin detección de vida (anti-spoofing) ni evaluación de sesgos demográficos.
