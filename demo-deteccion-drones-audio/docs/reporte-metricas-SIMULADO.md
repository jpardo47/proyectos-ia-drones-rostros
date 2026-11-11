# Reporte de métricas — P2 clasificador acústico drone / no_drone

**Estado: SIMULADO**

> **SIMULADO.** Estas cifras provienen de audio SINTÉTICO generado por `src/audio/synthetic.py` (tonos armónicos + ruido). Solo demuestran que el pipeline funciona de extremo a extremo. **No son rendimiento real** y no deben citarse como tal.

- Generado: 2026-11-11T19:43:51Z · modelo `p2-audio-logreg-6a565078f701` (logreg) · semilla 42
- Origen de datos: `simulation` · raíz: `data/interim/sintetico (SIMULADO)` · regla de etiquetas: `synthetic`
- Archivos por clase original: `{'drone': 12, 'no_drone': 12}`
- Archivos por etiqueta binaria: `{'drone': 12, 'no_drone': 12}` · grabaciones por etiqueta: `{'drone': 12, 'no_drone': 12}`
- Clases excluidas (sin mapear): `{}`
- Ventana 1.0 s, salto 0.5 s, 16000 Hz, 40 bandas mel, 20 MFCC

## División por grabación (sin fuga entre particiones)

| partición | grabaciones | ventanas | grabaciones drone | grabaciones no_drone |
|---|---|---|---|---|
| train | 16 | 112 | 8 | 8 |
| val | 4 | 28 | 2 | 2 |
| test | 4 | 28 | 2 | 2 |

Umbral calibrado en validación (máx. F1 por ventana): **0.50**. Decisión por grabación = media de probabilidades de sus ventanas ≥ umbral.

## Resultados en TEST (SIMULADO)

> Precaución: el test tiene solo 4 grabaciones; las cifras dependen mucho de la división. Si hay una sección de sensibilidad a la semilla al final, esa es la estimación más representativa.

| nivel | precisión | recall | F1 | especificidad | exactitud | n drone | n no_drone |
|---|---|---|---|---|---|---|---|
| por ventana | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 14 | 14 |
| por grabación | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 2 | 2 |

Matriz de confusión por ventana:

| real \ predicho | no_drone | drone |
|---|---|---|
| no_drone | 14 | 0 |
| drone | 0 | 14 |

Matriz de confusión por grabación:

| real \ predicho | no_drone | drone |
|---|---|---|
| no_drone | 2 | 0 |
| drone | 0 | 2 |

Desglose en test por clase original (decisión por grabación):

| clase original | grabaciones | predichas drone | prob. media |
|---|---|---|---|
| DRONE | 2 | 2 | 0.997 |
| NO_DRONE | 2 | 0 | 0.016 |

## Validación (usada para elegir el umbral; no es una estimación independiente)

| nivel | precisión | recall | F1 | especificidad | exactitud | n drone | n no_drone |
|---|---|---|---|---|---|---|---|
| por ventana | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 14 | 14 |
| por grabación | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 2 | 2 |

## Límites generales

- La clasificación de audio **no produce coordenadas, altura ni distancia**; las observaciones exportadas llevan `latitude`, `longitude` y `altitude` = null.
- El conjunto de test es pequeño: una o dos grabaciones mal clasificadas cambian mucho las métricas por grabación. No hay intervalos de confianza.
- Las ventanas de una misma grabación están correlacionadas; las métricas por ventana son optimistas respecto a su número efectivo de muestras.
- El modelo solo conoce las condiciones de grabación, micrófonos y tipos de dron/ruido presentes en el conjunto de entrenamiento; no se ha evaluado en campo ni en Popayán.
- Entorno: Python 3.11.9, CPU.
