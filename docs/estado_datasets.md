# Estado de datasets

Comprobación: 2026-11-11 (UTC, aprox. 19:20-19:35). Contenido verificado contra el disco y el registro `kit_descarga_datasets/estado_descargas.json`.

**Aviso OneDrive:** la raíz del proyecto está dentro de OneDrive. Los datasets descargados (~390 MB) se sincronizan con la nube. Están ignorados por git.

| Nombre | Proyecto | Origen (URL) | Licencia | Tamaño | Estado | Fecha comprobación (UTC) | Ubicación local |
|---|---|---|---|---|---|---|---|
| LFW funneled `lfw-funneled.tgz` | P1 `demo-reconocimiento-facial-uniface` | https://ndownloader.figshare.com/files/5976015 (Figshare/UMass) | Uso de investigación; licencia formal no verificada | 243 346 528 bytes (232.1 MiB) | Descargado, SHA256 verificado (coincide con el del kit), extraído: 13 248 archivos | 2026-11-11 19:33 | `demo-reconocimiento-facial-uniface/data/raw/lfw/` |
| LFW pares `pairs.txt`, `pairsDevTrain.txt`, `pairsDevTest.txt` | P1 | https://ndownloader.figshare.com/files/5976006, 5976012, 5976009 | Igual que LFW | ~0.2 MiB en total | Descargados, SHA256 verificado | 2026-11-11 19:33 | `demo-reconocimiento-facial-uniface/data/raw/lfw/` |
| Drone detection: audio WAV (90 archivos) | P2 `demo-deteccion-drones-audio` | https://github.com/DroneDetectionThesis/Drone-detection-dataset (`Data/Audio/`) | CC0-1.0 (API de GitHub y LICENSE del repositorio) | 158 764 512 bytes en total (151.4 MiB según el árbol del repositorio) | Descargado completo: 90/90 archivos con tamaño coincidente | 2026-11-11 19:33 | `demo-deteccion-drones-audio/data/raw/DroneDetectionThesis/Data/Audio/` |
| OpenStreetMap Colombia `colombia-latest.osm.pbf` | P3 `demo-localizacion-drones-popayan` | https://download.geofabrik.de/south-america/colombia-latest.osm.pbf | ODbL (OpenStreetMap / Geofabrik) | 334 218 299 bytes (318.7 MiB) | PENDIENTE: no descargado. No es necesario, el dashboard usa teselas públicas | 2026-11-11 19:20 | (no descargado) |
| NASA small UAV acoustics | P2 | https://data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip | PENDIENTE (licencia por confirmar) | 1 693 926 297 bytes (1615.5 MiB) | OMITIDO: no descargado, licencia no especificada | 2026-11-11 19:20 | (no descargado) |

Pendientes no automáticos: SRTM (OpenTopography), SIGPOP Popayán y CelebA. Ver `kit_descarga_datasets/INSTRUCCIONES.md`.

## Cómo consultar el progreso

- Estado actual: `python kit_descarga_datasets/monitor_descargas.py --una-vez`
- Seguimiento periódico: `python kit_descarga_datasets/monitor_descargas.py --intervalo 15` (termina cuando no quedan descargas activas). Escribe en `logs/descargas/monitor.log`.
- Logs de la descarga LFW: `logs/descargas/lfw.log` y `logs/descargas/lfw.err` (proceso PID 9744, ya terminado; se relanzó una vez tras un fallo del registro, y reanudó desde 205 MiB).
- Log de audio: `logs/descargas/audio.log`.
- Registro: `kit_descarga_datasets/estado_descargas.json`. Manifiesto: `kit_descarga_datasets/descargas_manifest.json`.

## Honestidad sobre procesos

Una descarga sigue tras cerrar Claude SOLO si se lanzó como proceso independiente del sistema operativo y el equipo sigue encendido. Ningún subagente continúa trabajando por sí mismo. Este estado se comprobó en el momento indicado; no se garantiza nada después.
