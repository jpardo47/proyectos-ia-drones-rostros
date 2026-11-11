# Inventario de datasets y licencias

Fecha de revisión: 2026-11-11. Este documento registra **origen y licencia**. El estado de
descarga (qué se ha bajado, sha256, tamaños) lo lleva el agente de descargas en
`docs/estado_datasets.md`.

Regla general: ningún dataset, peso, foto personal ni base SQLite se sube a git. Los datasets
van en `<proyecto>/data/raw/` (ignorado por git). Si una licencia no está confirmada, figura
como "no confirmada" y no se asume.

| Dataset | Proyecto | Fuente | Licencia | Condiciones de uso | Se sube a git | Notas |
|---|---|---|---|---|---|---|
| LFW (Labeled Faces in the Wild), `lfw-funneled.tgz` y pares `pairs.txt`, `pairsDevTrain.txt`, `pairsDevTest.txt` | P1 `demo-reconocimiento-facial-uniface` | Figshare (UMass). URLs en `kit_descarga_datasets/descargar_datasets.py` (`ndownloader.figshare.com/files/5976015` y similares). Página oficial: `vis-www.cs.umass.edu/lfw/` | **no confirmada** | No confirmadas en esta sesión: la página oficial no respondió (HTTP 000) y el kit la registra solo como "uso de investigación, licencia formal no verificada". Hasta confirmarla: solo evaluación de investigación, sin uso comercial, citando a los autores de LFW | No | Solo fotos de investigación. P1 no se relaciona con identificar personas que operan drones. Los pares se usan solo para evaluación. |
| Drone detection (IR, visible y audio) | P2 `demo-deteccion-drones-audio` | GitHub `DroneDetectionThesis/Drone-detection-dataset` (rama `master`) | CC0-1.0 (Creative Commons Zero v1.0 Universal). Confirmada con la API de GitHub el 2026-11-11 (`license.spdx_id`) | Dominio público según CC0. Sin restricciones de uso; se recomienda citar el origen | No | Repo no archivado, último push 2026-04-26, 344 estrellas. Incluye vídeos demo; el kit descarga la carpeta `Data`. |
| NASA small UAV acoustics | P2 `demo-deteccion-drones-audio` | `data.nasa.gov` (URL en el kit: `data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip`). No accesible desde esta sesión (HTTP 000) | **no confirmada** (el kit la marca "PENDIENTE") | No asumir dominio público hasta leer la página del dataset. El kit no la descarga (`--nasa` solo registra) | No | Pendiente de confirmar licencia antes de cualquier descarga. |
| OpenStreetMap Colombia (`colombia-latest.osm.pbf`) | P3 `demo-localizacion-drones-popayan` | Geofabrik `download.geofabrik.de/south-america/colombia-latest.osm.pbf` (~334 MB según el kit) | ODbL 1.0 (Open Database License), OpenStreetMap Foundation. Confirmada en `openstreetmap.org/copyright` | Atribución visible "© OpenStreetMap contributors" y enlace a la licencia. Si se publica una base de datos derivada, debe mantenerse ODbL (share-alike) | No | Se usa como referencia geográfica; los nodos `INST-SIM-*` son abstractos y no tienen coordenadas. |
| Teselas de OpenStreetMap (mapa del dashboard) | P3 `demo-localizacion-drones-popayan` (dashboard Streamlit + Folium) | Servidor de teselas de OSM. Política: `operations.osmfoundation.org/policies/tiles/` | Datos ODbL; uso de teselas regido por la política de la OSMF (no es una licencia de datos) | Atribución visible. User-Agent HTTP que identifique la aplicación. Prohibido descargar teselas en masa ("scraping") y enmascarar el User-Agent. Caché según cabeceras HTTP. Si el uso crece, usar un servidor propio o un proveedor comercial | No (no se guardan teselas en el repo) | Para uso intensivo, no depender del servidor público de OSM. |
| Datos sintéticos del simulador multisensor | P3 `demo-localizacion-drones-popayan` | Generados localmente por el simulador (código del propio proyecto) | Propios del proyecto (uso interno de la demo) | Siempre `is_simulated=true` / `data_origin="simulation"`; mostrar como SIMULADO en UI, CSV y GeoJSON. No son datos reales de drones, personas ni instalaciones | No para bases SQLite y CSV de ejecución (`data/runtime/`). Sí para código, escenarios y semillas | No representan alcance de ningún hardware. Pruebas de 100 m–10 km demuestran el software, no el alcance real. |

## Resumen de confirmación

- Confirmadas con fuente oficial en esta sesión: OSM/ODbL, política de teselas de OSM, y la licencia CC0-1.0 del repositorio de drones (API de GitHub).
- No confirmadas: LFW (página oficial no accesible desde esta sesión) y NASA small UAV acoustics (URL del kit no accesible; sin licencia especificada en el kit).
- Propios: datos sintéticos del simulador.
