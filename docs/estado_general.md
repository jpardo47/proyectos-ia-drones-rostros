# Estado general

Actualizado: 2026-11-11 (hora local de Colombia, tarde). Todo lo marcado como probado fue
ejecutado en este equipo; la columna "Pruebas ejecutadas" recoge la salida real.

Etiquetas: `IMPLEMENTADO_Y_PROBADO`, `IMPLEMENTADO_SIN_VALIDACION_COMPLETA`, `SIMULADO`,
`PREPARADO_NO_EJECUTADO`, `BLOQUEADO`, `PENDIENTE`.

## Resumen por proyecto

| Proyecto | Estado | Evidencia |
|---|---|---|
| P1 `demo-reconocimiento-facial-uniface` | `IMPLEMENTADO_Y_PROBADO` (interfaz Streamlit: solo arranque) | 17 pruebas aprobadas; demo CLI detecta 1 rostro en la foto de muestra y escribe CSV; evaluación acotada en LFW |
| P2 `demo-deteccion-drones-audio` | `IMPLEMENTADO_Y_PROBADO` con datos reales (dataset pequeño) | 26 pruebas aprobadas; entrenamiento y evaluación con 90 grabaciones reales |
| P3 `demo-localizacion-drones-popayan` | `IMPLEMENTADO_Y_PROBADO` en modo simulación, incluidas las imágenes de Blender | 338 pruebas aprobadas, ninguna saltada (incluye los 12 escenarios obligatorios y la verificación de etiquetas YOLO contra píxeles); 10 escenarios de extremo a extremo; API y dashboard vistos funcionando |
| Descargas | LFW y audio descargados y verificados; OSM y NASA pendientes a propósito | SHA256 de LFW comprobado; 90 WAV contados |

## Línea A — Descargas y Skills

| Agente responsable | Modelo realmente utilizado | Proyecto | Tarea | Estado | Dependencias | Archivos creados | Pruebas ejecutadas | Errores | Siguiente acción |
|---|---|---|---|---|---|---|---|---|---|
| `gestor-descarga-datasets` | `claude-haiku-5-5` | los tres | Mejorar el kit, verificar URLs y licencias, descargar, extraer, registrar | `IMPLEMENTADO_Y_PROBADO` | kit original | `kit_descarga_datasets/descargar_datasets.py` (reescrito), `monitor_descargas.py`, `INSTRUCCIONES.md`, `docs/estado_datasets.md`, `logs/descargas/*` | `--verificar` (90/90 audios disponibles, LFW con rangos); descarga real de audio (90 WAV, 0 fallos) y de LFW; monitor `--una-vez`. Comprobado después por el coordinador: SHA256 de `lfw-funneled.tgz` = `b47c8422…100a` (coincide), 30 DRONE + 30 HELICOPTER + 30 BACKGROUND, 0 archivos `.parcial` | La primera descarga de LFW murió a 190/232 MiB por un fallo del registro con dos procesos a la vez; se corrigió y la descarga se reanudó desde 205 MiB. Dos procesos simultáneos aún pueden pisarse el registro de estado | Ejecutar `--verificar` para reconciliar el registro; decidir si se descarga OSM Colombia (319 MiB) y confirmar la licencia de NASA (1,6 GB) |
| `ingeniero-datos-skills` | `claude-haiku-5-5` | transversal | Revisar e instalar Skills; inventario de licencias | `IMPLEMENTADO_Y_PROBADO` | `find-skills` | `docs/skills-inventory.md`, `docs/datasets.md`, `.claude/skills/python-testing-patterns`, `.claude/skills/github-actions-templates`, `skills-lock.json`, P3 `.env.example` | `npx skills list` (2 Skills de proyecto); `npx skills list -g` (find-skills) | Instaló `fastapi/fastapi@fastapi` antes de mirar la tabla de riesgo (la CLI la marca riesgo alto) y la retiró a continuación. Las licencias de LFW y NASA quedaron "no confirmada" (sus páginas no respondieron) | Reiniciar Claude Code para cargar las Skills de proyecto; confirmar licencia de LFW en su página oficial |

`find-skills` (vercel-labs/skills, MIT) la instaló el coordinador de forma global en
`~/.claude/skills/find-skills`; Claude Code ya la reconoce. Evaluación de riesgo que mostró la
CLI: Gen "Safe", Socket "0 alerts", Snyk "Med Risk". No se instalaron Skills de audio, Blender ni
geoespaciales: las encontradas tienen muy pocas instalaciones o autores sin reputación verificable.

## Línea B — Proyecto 3 (Popayán)

| Agente responsable | Modelo realmente utilizado | Tarea | Estado | Dependencias | Archivos creados | Pruebas ejecutadas | Errores | Siguiente acción |
|---|---|---|---|---|---|---|---|---|
| Coordinador (sesión principal) | `claude-fable-5-2` | Contratos, interfaces, 7 nodos ficticios, entorno, integración y revisión | `IMPLEMENTADO_Y_PROBADO` | plan maestro | `src/contracts/*`, `contracts/observation.schema.json`, `data/stations/estaciones_ficticias.json`, `requirements.txt`, `pytest.ini` | Prueba de humo contrato ↔ JSON Schema; 10 escenarios de extremo a extremo; API en vivo con `curl`; dashboard en navegador | — | Decidir cambios de contrato propuestos (ver abajo) |
| `ingeniero-simulacion-blender` | `claude-sonnet-5-5` | Simulador, sensores virtuales, Remote ID ficticio, 10 escenarios, CLI, Blender | Simulador `IMPLEMENTADO_Y_PROBADO` (`SIMULADO`); Blender `IMPLEMENTADO_Y_PROBADO` tras la corrección del coordinador | contratos; Blender 4.4.3 | `src/simulation/*`, `blender/generate_scene.py`, `tests/simulation/`, `tests/blender/`, `docs/simulacion.md`, `data/synthetic/examples/basico.json`, `data/synthetic/examples/blender/` (4 PNG + 4 etiquetas + manifiesto) | Simulación: 23 aprobadas. Blender: 15 aprobadas. CLI `basico` semilla 42: 3 drones, 7 nodos, 2607 eventos | El agente no pudo ejecutar Blender (no había `blender.exe`). Tras instalar Blender 4.4.3 con winget, el coordinador ejecutó el generador: el motor Workbench cerró Blender por un fallo de shaders, y la ruta relativa de salida dejó los PNG fuera del proyecto. Reasignación documentada: el coordinador cambió el render a Cycles por CPU, la ruta a absoluta y la caja a los vértices reales, y añadió una prueba que contrasta cada etiqueta con los píxeles (desvío máximo 2,6 px) | Generar más variedad (fondos, distancias, oclusiones) si se quiere usar para entrenar |
| `ingeniero-remote-id` | `claude-opus-5-5` | Parser, validación, conversión, agentes de ingesta y validación, adaptadores | `IMPLEMENTADO_Y_PROBADO`; adaptador de recepción física `PREPARADO_NO_EJECUTADO` a propósito (solo interfaz) | contratos | `src/remote_id/*`, `src/ingestion/*`, `data/examples/remote_id/*.jsonl`, `docs/adaptador-recepcion.md`, `tests/remote_id/`, `tests/ingestion/` | 189 aprobadas | — | — |
| `ingeniero-fusion-decisiones` | `claude-opus-5-5` | Deduplicación, correlación, seguimiento, motor de estados, alertas, auditoría | `IMPLEMENTADO_Y_PROBADO` | contratos; ingesta | `src/correlation/*`, `src/tracking/*`, `src/decision_agents/*`, `src/audit/*`, `docs/motor-decisiones.md`, tests correspondientes | 61 aprobadas, incluidas 5 regresiones de fragmentación | Primera versión: 294 tracks para 3 drones (cada detección de radar anónima abría un track). Detectado en la integración, devuelto al agente y corregido: 11 tracks, 33 decisiones, 10 alertas | Afinar la puerta de asociación: quedan 3 tracks de radar de 1–2 puntos y 15 observaciones sin asociar por ambigüedad en `basico` |
| `ingeniero-api-dashboard` | `claude-sonnet-5-5` | SQLite, registro de estaciones, orquestación, API, dashboard, `app.py`, README | API y almacenamiento `IMPLEMENTADO_Y_PROBADO`; dashboard `IMPLEMENTADO_SIN_VALIDACION_COMPLETA` | contratos; los otros tres módulos | `src/storage/*`, `src/stations/*`, `src/orchestration/*`, `src/api/*`, `src/dashboard/app.py`, `app.py`, `README.md`, tests correspondientes | 35 aprobadas. Coordinador: servidor real en el puerto 8011 (`/health`, estaciones, GeoJSON sin `INST-SIM`, 401 sin token, 422 para audio con coordenadas); dashboard abierto en navegador (mapa con teselas OSM, banner SIMULADO, 6 pestañas, formulario de revisión) | El dashboard escuchaba en todas las interfaces de red; el coordinador lo limitó a `127.0.0.1` en `app.py` | Probar a mano la revisión de una alerta y las descargas desde el navegador |

Resultados reales de los 10 escenarios (semilla 42, ejecutados por el coordinador):

| Escenario | Eventos | Rechazados | Duplicados | Tracks | Alertas | Estados alcanzados |
|---|---|---|---|---|---|---|
| `basico` | 2607 | 0 | 165 | 11 | 10 | POSIBLE, CORROBORADA, PERDIDO |
| `sin_remote_id` | 1091 | 0 | 237 | 10 | 8 | POSIBLE, CORROBORADA, PERDIDO |
| `duplicados` | 1384 | 0 | 1767 | 9 | 6 | POSIBLE, CORROBORADA, PERDIDO |
| `contradictorio` | 1184 | 0 | 0 | 6 | 2 | POSIBLE, **REQUIERE_REVISION**, PERDIDO |
| `corroborado` | 1246 | 0 | 0 | 9 | 4 | POSIBLE, **CORROBORADA**, PERDIDO |
| `perdida_senal` | 1740 | 0 | 21 | 7 | 4 | POSIBLE, CORROBORADA, **PERDIDO** |
| `estacion_caida` | 1494 | 240 (`STATION_OFFLINE`) | 12 | 6 | 2 | POSIBLE, CORROBORADA, PERDIDO |
| `malformados` | 2233 | 28 (8 códigos distintos) | 53 | 8 | 6 | POSIBLE, CORROBORADA, PERDIDO |
| `sin_estacion_control` | 3371 | 0 | 171 | 11 | 8 | POSIBLE, CORROBORADA, PERDIDO |
| `rangos_100m_10km` | 3987 | 0 | 995 | 15 | 20 | POSIBLE, CORROBORADA, PERDIDO |

En los diez: ninguna observación acústica con posición, ningún nodo `INST-SIM` con coordenadas,
ninguna observación no simulada. Al terminar cada escenario todos los tracks quedan en
`SEGUIMIENTO_PERDIDO` porque la demo agota el tiempo de caducidad.

## Línea C — Proyectos 1 y 2

| Agente responsable | Modelo realmente utilizado | Proyecto | Tarea | Estado | Dependencias | Archivos creados | Pruebas ejecutadas | Errores | Siguiente acción |
|---|---|---|---|---|---|---|---|---|---|
| `ingeniero-uniface` | `claude-sonnet-5-5` | P1 | Detección, embeddings, galería, comparación, CSV, UI | `IMPLEMENTADO_Y_PROBADO`; `app.py` `IMPLEMENTADO_SIN_VALIDACION_COMPLETA` | UniFace 4.3.0 (pesos públicos); LFW para evaluar | `src/*`, `scripts/demo_cli.py`, `scripts/eval_lfw_pairs.py`, `app.py`, `tests/*`, `README.md`, `requirements.txt` | 17 aprobadas (repetido por el coordinador). Demo CLI: 1 rostro, `desconocido` con galería vacía, CSV escrito. LFW, 200 pares de `pairsDevTest.txt`: exactitud 0,975 con umbral 0,4 | La evaluación es acotada (primeros 100 pares positivos y 100 negativos), no el protocolo de 10 particiones. La interfaz solo se arrancó (HTTP 200); no se probó subir una foto | Evaluación completa de LFW; probar la interfaz a mano |
| `ingeniero-audio-ia` | `claude-opus-5-5` | P2 | Features, clasificador, división por grabación, evaluación, exportación a P3, API | `IMPLEMENTADO_Y_PROBADO` con datos reales | audio descargado por la línea A | `src/audio/*`, `src/models/*`, `src/export/observations.py`, `scripts/{train,evaluate,predict}.py`, `app.py`, `tests/*`, `docs/reporte-metricas.md`, `README.md` | 26 aprobadas (repetido por el coordinador). Test real (18 grabaciones, semilla 42): F1 por ventana 0,865; por grabación 1,000. **Con 5 semillas: F1 por grabación ≈ 0,82 de media, rango 0,44–1,00.** Predicciones comprobadas por el coordinador en DRONE_005 (0,99), HELICOPTER_007 y BACKGROUND_011 (≈0) | La semilla 42 es una división favorable; la cifra representativa es la media. Dataset de 90 clips de un solo entorno; sin metadatos de sesión, puede haber fuga entre particiones | Más datos y de más entornos; validación cruzada por grupos; la API no se arrancó en vivo |

Lo generado con audio sintético está aparte en `docs/reporte-metricas-SIMULADO.md` y no es
rendimiento real.

## Calidad (Hito D)

| Agente responsable | Modelo realmente utilizado | Tarea | Estado | Archivos | Pruebas ejecutadas | Siguiente acción |
|---|---|---|---|---|---|---|
| `ingeniero-qa-devops` | `claude-haiku-5-5` | 12 escenarios obligatorios como pruebas de integración, CI | Pruebas `IMPLEMENTADO_Y_PROBADO`; workflows `PREPARADO_NO_EJECUTADO` | P3 `tests/integration/test_escenarios_obligatorios.py` y `conftest.py`; `.github/workflows/p1-uniface.yml`, `p2-audio.yml`, `p3-popayan.yml` | P1 17 aprobadas; P2 26 aprobadas; P3 333 aprobadas y 1 saltada en su ejecución (15 de integración, los 12 escenarios aprobados); tras generar las imágenes de Blender, el coordinador obtuvo 338 aprobadas y 0 saltadas. Ruff en P3: 277 avisos de estilo, sin corregir | El agente no escribió `docs/reporte-pruebas.md`; lo redactó el coordinador con las salidas reales. Ejecutar los workflows al publicar en GitHub |

## Cómo se ejecutaron los subagentes

- Los diez archivos de `.claude/agents/` se crearon durante esta sesión. Claude Code carga los
  tipos de agente al iniciar, así que **no se invocaron por su nombre nativo**: cada uno se lanzó
  como agente de propósito general con el modelo fijado (`haiku`, `sonnet`, `opus`) y la
  instrucción de leer y seguir su archivo de definición. Tras reiniciar Claude Code estarán
  disponibles por nombre.
- El modelo "realmente utilizado" es el identificador que cada agente leyó en su propio prompt de
  sistema y reportó. No hubo sustituciones.
- `arquitecto-revisor` (Fable) está definido pero **no se ejecutó como subagente**: la revisión la
  hizo la sesión principal, que corre en `claude-fable-5-2`.

## Bloqueos reales

1. **Blender.** Resuelto el 2026-11-11: se instaló Blender 4.4.3 con winget (con autorización
   del usuario) y se generaron 4 imágenes con etiquetas YOLO verificadas. Queda una limitación:
   el motor Workbench no funciona en modo `--background` en este equipo; se usa Cycles por CPU.
2. **GitHub.** `gh` no está instalado y no hay remoto configurado: nada se ha publicado. Todos los
   commits son locales, con autor único `jpardo47` y sin líneas de coautoría.
3. **OneDrive.** La carpeta del proyecto se sincroniza con la nube: los ~390 MB de datasets y las
   13 248 imágenes de LFW también. Los entornos virtuales se pusieron fuera
   (`C:\Users\<usuario>\.venvs\`) para no sincronizar miles de archivos.

## Cambios de contrato propuestos por los agentes (sin aplicar)

- `RejectedInput.stage`: añadir `"pipeline"` para los rechazos del motor (hoy van como `"validation"`).
- `Track.track_kind`: `"posicional"` / `"presencia"` para que el dashboard los distinga.
- `RejectedInput.received_at_utc` opcional (hoy se usa 1970-01-01 como marcador cuando no hay hora).
- `ReportedLocation` con límites de latitud y longitud (hoy los comprueba el validador).

## Pendiente del plan maestro

- Publicación en GitHub (requiere autenticación y autorización expresa).
- Antes de publicar: sustituir las rutas con el nombre de usuario local que aparecen en algunos
  README y docs.
- Capa cartográfica sin conexión de Popayán (hoy el mapa usa teselas públicas en línea).
- Conectar la exportación de P2 con la ingesta de P3 en una prueba conjunta.
