# Kit de descarga de datasets: Proyectos IA / Popayán

Este kit **no contiene los datasets**. Descarga los archivos desde sus fuentes oficiales.
Solo usa la biblioteca estándar de Python 3.10 o superior.

## Destino

Por defecto, los datos se guardan en la **carpeta padre de este kit** (la raíz de
`Proyectos_IA_Drones_Rostros`). Ya no se intenta adivinar el Escritorio.
Con `--dest "RUTA"` se usa otra carpeta raíz. Las rutas definitivas son:

| Dataset | Ruta dentro de la raíz |
|---|---|
| LFW (rostros) | `demo-reconocimiento-facial-uniface/data/raw/lfw/` |
| Audio de drones | `demo-deteccion-drones-audio/data/raw/DroneDetectionThesis/` |
| Cartografía OSM Colombia | `demo-localizacion-drones-popayan/data/raw/` |

**Aviso OneDrive:** la raíz del proyecto está dentro de OneDrive. Lo descargado se
sincroniza con la nube. Los datasets están ignorados por git, pero sí se suben a OneDrive.

## Uso básico

```bash
python descargar_datasets.py            # igual que --basicos
python descargar_datasets.py --basicos  # LFW + audio de drones (~392 MB)
```

En Windows también puedes hacer doble clic en `DESCARGAR_BASICOS_WINDOWS.bat`.

## Opciones

| Opción | Qué hace |
|---|---|
| `--basicos` | LFW + audio de drones (por defecto). |
| `--lfw` | Solo LFW (`lfw-funneled.tgz` ~233 MB + 3 archivos de pares). |
| `--audio` | Solo audio de drones: 90 WAV, ~159 MB, sin videos. |
| `--audio --muestra-audio N` | Solo los primeros N audios. |
| `--osm` | Cartografía OSM Colombia (`colombia-latest.osm.pbf`, ~334 MB). |
| `--todos` | LFW + audio + OSM. Supera 500 MB: exige `--permitir-grandes`. |
| `--nasa` | No descarga nada. Registra el dataset NASA como omitido: su licencia no está especificada y pesa ~1.69 GB. |
| `--verificar` | Solo comprueba URLs, tamaños y disponibilidad (GET con `Range: bytes=0-0`). No descarga nada y actualiza el registro. |
| `--extraer` | Tras descargar LFW, extrae `lfw-funneled.tgz` con validación de rutas (nada sale del destino). |
| `--permitir-grandes` | Permite lotes de más de 500 MB. |
| `--dest RUTA` | Carpeta raíz de destino. |

Ejemplos:

```bash
python descargar_datasets.py --verificar
python descargar_datasets.py --lfw --extraer
python descargar_datasets.py --audio
python descargar_datasets.py --todos --permitir-grandes --dest "D:\Datasets_IA"
```

## Comportamiento

- **Comprobación previa:** antes de descargar se consulta el tamaño y el estado HTTP. Se comprueba el
  espacio libre del disco (con 1 GB de margen). Un lote de más de 500 MB se rechaza salvo `--permitir-grandes`.
- **Reanudación:** un archivo interrumpido queda como `*.parcial`. La siguiente ejecución continúa
  con `Range` si el servidor responde 206. Si responde 200, reinicia desde cero.
- **Reintentos:** máximo 3 intentos por archivo, con espera de 5 s y 10 s.
- **Integridad:** LFW se verifica con su SHA256 oficial. Los WAV se verifican por tamaño
  (el de la API de GitHub) y se registra su SHA256.
- **No repetir:** un archivo ya completo y verificado no se vuelve a descargar.
- **Registro:** `kit_descarga_datasets/estado_descargas.json`, actualizado durante la descarga
  (cada ~3 s). Manifiesto final: `kit_descarga_datasets/descargas_manifest.json`.

## Seguimiento del progreso

```bash
python monitor_descargas.py --una-vez    # estado actual
python monitor_descargas.py              # cada 15 s hasta que no quedan descargas activas
python monitor_descargas.py --intervalo 5
```

El monitor escribe en `logs/descargas/monitor.log` (carpeta de la raíz del proyecto).

Las descargas largas pueden lanzarse como proceso independiente, con su propio log:

```powershell
Start-Process -WindowStyle Hidden -FilePath python -ArgumentList '-u','descargar_datasets.py','--lfw','--extraer' `
  -WorkingDirectory '<ruta del kit>' -RedirectStandardOutput '<raiz>\logs\descargas\lfw.log' `
  -RedirectStandardError '<raiz>\logs\descargas\lfw.err' -PassThru
```

Un proceso lanzado así sigue mientras el equipo esté encendido y no se cierre la sesión.
Cerrar Claude no lo detiene. Anota el PID que devuelve `-PassThru`.

## Fuentes no automáticas

- **SRTM (elevación):** https://portal.opentopography.org/datasetMetadata?otCollectionID=OT.042013.4326.1
  (elige el área de interés y respeta los requisitos de acceso).
- **SIGPOP Popayán:** https://sig.popayan.gov.co/ (la exportación depende de la capa).
- **OpenDroneID:** es software, no un dataset. https://github.com/opendroneid/opendroneid-core-c
- **CelebA:** dataset grande de uso condicionado por su licencia; no incluido.

## Importante

- Los tamaños y enlaces externos pueden cambiar. La descarga requiere internet en TU equipo.
- No compartas públicamente imágenes personales ni datos de instalaciones institucionales.
- Las ubicaciones de estaciones del simulador deben ser ficticias, no datos operativos reales.
- No subas los datasets a repositorios git.
