## Dataset real: DroneDetectionThesis (audio)

- Ubicación local: `data/raw/DroneDetectionThesis/Data/Audio/` (descargado por `gestor-descarga-datasets`; no se sube a git).
- Estructura inspeccionada (2026-11-11): **90 WAV**, todos de 10,0 s, 44,1 kHz, estéreo, PCM 16 bits.
  Nombres `BACKGROUND_001..030`, `DRONE_001..030`, `HELICOPTER_001..030`. No hay otras carpetas ni metadatos.
- Etiquetas leídas del prefijo del nombre (no supuestas): 30 `DRONE` → `drone`; 30 `HELICOPTER` + 30
  `BACKGROUND` → `no_drone` (mapa en `config/label_map_dronedetectionthesis.json`).
  Clase negativa: existe y es real (60 clips); no se fabricaron negativos.
- Cada archivo se trata como una grabación (grupo). La división es por archivo, estratificada por
  clase original: 60 train / 12 val / 18 test (6 DRONE, 6 HELICOPTER, 6 BACKGROUND en test).

### Sensibilidad a la división (misma configuración, distintas semillas) — datos reales

El test tiene solo 18 grabaciones, así que el resultado depende mucho de qué clips caen en test.
La semilla 42 (modelo publicado) resultó ser una de las divisiones **favorables**:

| modelo | semilla | umbral | F1 ventana | P grabación | R grabación | F1 grabación | matriz grabación [[TN,FP],[FN,TP]] |
|---|---|---|---|---|---|---|---|
| logreg | 42 (publicado) | 0.44 | 0.865 | 1.000 | 1.000 | 1.000 | [[12,0],[0,6]] |
| logreg | 1 | 0.75 | 0.732 | 0.800 | 0.667 | 0.727 | [[11,1],[2,4]] |
| logreg | 2 | 0.53 | 0.649 | 0.667 | 0.333 | 0.444 | [[11,1],[4,2]] |
| logreg | 3 | 0.60 | 0.807 | 1.000 | 0.833 | 0.909 | [[12,0],[1,5]] |
| logreg | 4 | 0.55 | 0.921 | 1.000 | 1.000 | 1.000 | [[12,0],[0,6]] |
| rf | 42 | 0.38 | 0.871 | 0.857 | 1.000 | 0.923 | [[11,1],[0,6]] |

Media de F1 por grabación (logreg, 5 semillas): **≈ 0,82** (rango 0,44–1,00); F1 por ventana ≈ 0,80
(rango 0,65–0,92). Esta cifra es más representativa que el 1,00 de la semilla 42. Los errores más
frecuentes son drones no detectados (FN); los falsos positivos vinieron de `BACKGROUND`, no de
`HELICOPTER` en estas corridas.

### Sesgos y límites específicos

- **Muy pequeño**: 30 clips por clase original; 6 drones en test. Un clip cambia el recall en 0,17.
- **Posible fuga por sesión**: los clips de 10 s pueden proceder de las mismas sesiones/lugares de
  grabación largas; el dataset no trae metadatos de sesión, así que no se puede agrupar por sesión.
  Si hay clips contiguos de una misma grabación en train y test, las métricas son optimistas.
- **Condiciones de grabación**: un solo dataset, con su micrófono, entorno y tipos de dron; no
  representa el ruido urbano de Popayán, viento fuerte, lluvia, tráfico ni otros modelos de dron.
- **Clases presentes**: solo dron, helicóptero y fondo. No hay aviones, motos, cortadoras, aves,
  insectos ni otros zumbidos que en la práctica serían falsos positivos probables.
- **Umbral** calibrado en 12 grabaciones de validación: inestable (0,44–0,75 según semilla).
- La salida es una puntuación de clasificador, no una probabilidad calibrada de presencia de dron.
