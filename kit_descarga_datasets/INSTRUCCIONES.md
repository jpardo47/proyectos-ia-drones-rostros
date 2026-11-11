# Kit de descarga de datasets — Proyectos IA / Popayán

Este kit **no contiene los datasets**; descarga archivos desde sus fuentes cuando se ejecuta en un computador con internet. No necesitas instalar bibliotecas de Python adicionales para el descargador.

## Descarga inicial recomendada

1. Instala Python 3.10 o superior.
2. Descomprime este kit.
3. En Windows, haz doble clic en `DESCARGAR_BASICOS_WINDOWS.bat`. Alternativamente, abre una terminal en esta carpeta y ejecuta:

```bash
python descargar_datasets.py --basicos
```

La descarga crea `Proyectos_IA_Drones_Rostros` en tu Escritorio (o, si no existe un Escritorio reconocible, en la carpeta actual). Puedes indicar una carpeta exacta con `--dest`.

## Todas las descargas automáticas disponibles

```bash
python descargar_datasets.py --todos
```

Incluye LFW y audio desde GitHub, además de cartografía de toda Colombia (aprox. 318 MB). **La opción `--todos` no incluye NASA**, que debes solicitar aparte si te interesa, ya que su descarga puede cambiar de enlace y la licencia no está especificada.

Otras opciones:

```bash
python descargar_datasets.py --lfw
python descargar_datasets.py --audio
python descargar_datasets.py --audio --muestra-audio 10
python descargar_datasets.py --osm
python descargar_datasets.py --nasa
python descargar_datasets.py --todos --dest "D:\\Datasets_IA"
```

Las descargas parciales o fallidas se pueden reintentar ejecutando nuevamente el comando. Los archivos completos no se descargan otra vez; LFW utiliza hashes SHA256 oficiales para comprobar integridad. Se crea un registro `descargas_manifest.json`.

## Qué descarga el kit

- **LFW (rostros)**: archivo `lfw-funneled.tgz` + pares de evaluación, desde Figshare/Scikit-learn.
- **Audio de drones**: consulta el árbol público de GitHub del repositorio DroneDetectionThesis/Drone-detection-dataset y descarga únicamente archivos de audio. No descarga sus 650 videos.
- **OpenStreetMap Colombia**: archivo `colombia-latest.osm.pbf` desde Geofabrik, solo con `--todos` o `--osm`.
- **NASA audio**: opción `--nasa` separada; la URL redirige al proveedor de almacenamiento y podría fallar temporalmente.

## Descargas que no son automáticas

- **SRTM (elevación)**: https://portal.opentopography.org/datasetMetadata?otCollectionID=OT.042013.4326.1 (escoge el área de interés y respeta requisitos de acceso).
- **SIGPOP Popayán**: https://sig.popayan.gov.co/ (la posibilidad de exportar depende de la capa).
- **OpenDroneID**: es software, no un dataset. https://github.com/opendroneid/opendroneid-core-c
- **CelebA**: dataset grande de uso condicionado por su licencia y requisitos del sitio; no incluido en el descargador.

## Importante

- Los tamaños y enlaces externos pueden cambiar. La descarga requiere internet en TU equipo.
- No compartas públicamente imágenes personales ni datos de instalaciones institucionales.
- Las ubicaciones de estaciones del simulador deben ser ficticias, no datos operativos reales.
- No incluyas los datasets grandes en tus repositorios GitHub.
