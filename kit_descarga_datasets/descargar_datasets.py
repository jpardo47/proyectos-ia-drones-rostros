#!/usr/bin/env python3
"""Descargas de datasets públicos para tres proyectos IA (sin dependencias externas).
Uso: python descargar_datasets.py --basicos
     python descargar_datasets.py --todos
     python descargar_datasets.py --basicos --dest "C:\\mi_carpeta"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

LFW_URL = "https://ndownloader.figshare.com/files/5976015"
LFW_SHA256 = "b47c8422c8cded889dc5a13418c4bc2abbda121092b3533a83306f90d900100a"
LFW_PAIRS = {
    "pairsDevTrain.txt": ("https://ndownloader.figshare.com/files/5976012", "1d454dada7dfeca0e7eab6f65dc4e97a6312d44cf142207be28d688be92aabfa"),
    "pairsDevTest.txt": ("https://ndownloader.figshare.com/files/5976009", "7cb06600ea8b2814ac26e946201cdb304296262aad67d046a16a7ec85d0ff87c"),
    "pairs.txt": ("https://ndownloader.figshare.com/files/5976006", "ea42330c62c92989f9d7c03237ed5d591365e89b3e649747777b70e692dc1592"),
}
GITHUB_TREE = "https://api.github.com/repos/DroneDetectionThesis/Drone-detection-dataset/git/trees/master?recursive=1"
RAW_BASE = "https://raw.githubusercontent.com/DroneDetectionThesis/Drone-detection-dataset/master/"
OSM_URL = "https://download.geofabrik.de/south-america/colombia-latest.osm.pbf"
NASA_URL = "https://data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip"
USER_AGENT = "DatasetPreparation/1.0 (educational research; data download)"


def root_folder() -> Path:
    home = Path.home()
    options = [home / 'Desktop', home / 'Escritorio', home / 'OneDrive' / 'Desktop', home / 'OneDrive' / 'Escritorio']
    for p in options:
        if p.is_dir():
            return p / 'Proyectos_IA_Drones_Rostros'
    return Path.cwd() / 'Proyectos_IA_Drones_Rostros'


def request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json, application/octet-stream, */*"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, checksum: str | None = None, attempts: int = 3) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size:
        current_hash = sha256_file(destination) if checksum else None
        if not checksum or current_hash == checksum:
            print(f"[YA EXISTE] {destination}")
            return {"status":"exists", "path":str(destination), "bytes":destination.stat().st_size, "sha256":current_hash or sha256_file(destination), "url":url}
        print(f"[AVISO] Hash inesperado en archivo existente: {destination}. Se descargará de nuevo.")
    tmp = destination.with_name(destination.name + '.parcial')
    for attempt in range(1, attempts + 1):
        try:
            print(f"[DESCARGANDO] {destination.name} (intento {attempt}/{attempts})")
            with urllib.request.urlopen(request(url), timeout=55) as resp, tmp.open('wb') as out:
                size = int(resp.headers.get('Content-Length') or 0)
                written = 0
                last_print = time.monotonic()
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    if time.monotonic() - last_print > 4:
                        print(f"    {written / (1024**2):.1f} MiB" + (f" / {size / (1024**2):.1f} MiB" if size else ""), flush=True)
                        last_print = time.monotonic()
            if not tmp.stat().st_size:
                raise RuntimeError('La descarga quedó vacía')
            digest = sha256_file(tmp)
            if checksum and digest != checksum:
                raise ValueError(f"SHA256 no coincide para {destination.name}: {digest}")
            tmp.replace(destination)
            print(f"[OK] {destination.name}: {destination.stat().st_size/(1024**2):.1f} MiB")
            return {"status":"downloaded", "path":str(destination), "bytes":destination.stat().st_size, "sha256":digest, "url":url}
        except Exception as exc:
            print(f"[ERROR] {type(exc).__name__}: {exc}")
            if attempt < attempts:
                time.sleep(attempt * 2)
        finally:
            if tmp.exists():
                tmp.unlink()
    return {"status":"failed", "path":str(destination), "url":url}


def get_json(url: str):
    with urllib.request.urlopen(request(url), timeout=30) as response:
        return json.load(response)


def download_lfw(base: Path) -> list[dict]:
    folder = base / 'demo-reconocimiento-facial-uniface' / 'data' / 'raw' / 'lfw'
    results = [download(LFW_URL, folder / 'lfw-funneled.tgz', LFW_SHA256)]
    for filename, (url, sha) in LFW_PAIRS.items():
        results.append(download(url, folder / filename, sha))
    return results


def download_audio(base: Path, limit: int | None) -> list[dict]:
    folder = base / 'demo-deteccion-drones-audio' / 'data' / 'raw' / 'DroneDetectionThesis'
    print('[INFO] Consultando árbol público del repositorio para descargar SOLO audio (no videos).')
    try:
        tree = get_json(GITHUB_TREE)
        if tree.get('truncated'):
            print('[AVISO] Árbol GitHub truncado; puede faltar parte de los archivos.')
        extensions = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aiff', '.aif'}
        paths = sorted({row['path'] for row in tree.get('tree', []) if row.get('type') == 'blob' and Path(row['path']).suffix.lower() in extensions and 'audio' in [part.lower() for part in Path(row['path']).parts]})
        if not paths:
            raise RuntimeError('No se encontraron grabaciones en carpetas Audio. Revisar estructura del repositorio.')
    except Exception as exc:
        print(f'[ERROR] Imposible listar las grabaciones: {exc}')
        return [{"status":"failed", "path":"audio", "detail":str(exc), "url":GITHUB_TREE}]
    print(f'[INFO] Grabaciones detectadas: {len(paths)}. Descargando {min(len(paths), limit) if limit else len(paths)}.')
    if limit:
        paths = paths[:limit]
    results = []
    for i, path in enumerate(paths, 1):
        print(f'[AUDIO {i}/{len(paths)}] {path}')
        safe_path = Path(*Path(path).parts)
        url = RAW_BASE + urllib.parse.quote(path, safe='/')
        results.append(download(url, folder / safe_path, attempts=2))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description='Descarga datasets públicos para proyectos IA de Popayán.')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--basicos', action='store_true', help='LFW y audio de drones (por defecto).')
    actions.add_argument('--todos', action='store_true', help='LFW, audio de drones y cartografía Colombia (archivo grande).')
    actions.add_argument('--lfw', action='store_true', help='Solo LFW.')
    actions.add_argument('--audio', action='store_true', help='Solo audio de drones.')
    actions.add_argument('--osm', action='store_true', help='Solo cartografía Colombia (318 MB aproximadamente).')
    actions.add_argument('--nasa', action='store_true', help='Solo dataset acústico NASA (el enlace puede requerir redirección).')
    parser.add_argument('--dest', type=Path, default=root_folder(), help='Carpeta principal de destino.')
    parser.add_argument('--muestra-audio', type=int, default=0, help='Descarga solo los primeros N audios (0=todos).')
    args = parser.parse_args()
    base = args.dest.expanduser().resolve()
    print(f'[DESTINO] {base}')
    selections = []
    if args.lfw or args.basicos or args.todos or not any((args.audio, args.osm, args.nasa)):
        selections.append('lfw')
    if args.audio or args.basicos or args.todos or not any((args.lfw, args.osm, args.nasa)):
        selections.append('audio')
    if args.osm or args.todos:
        selections.append('osm')
    if args.nasa:
        selections.append('nasa')
    results: list[dict] = []
    for item in selections:
        if item == 'lfw':
            results += download_lfw(base)
        elif item == 'audio':
            results += download_audio(base, args.muestra_audio or None)
        elif item == 'osm':
            output = base / 'demo-localizacion-drones-popayan' / 'data' / 'raw' / 'colombia-latest.osm.pbf'
            results.append(download(OSM_URL, output))
        elif item == 'nasa':
            output = base / 'demo-deteccion-drones-audio' / 'data' / 'raw' / 'nasa_small_uav_acoustics.zip'
            results.append(download(NASA_URL, output))
    manifest = base / 'descargas_manifest.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"generated_utc": datetime.now(timezone.utc).isoformat(), "destination":str(base), "results":results}, indent=2, ensure_ascii=False), encoding='utf-8')
    ok = sum(r['status'] in ('downloaded','exists') for r in results)
    failed = len(results) - ok
    print(f'\n[RESUMEN] {ok} archivos disponibles, {failed} fallidos. Registro: {manifest}')
    if failed:
        print('Revisa tu conexión, permisos y los mensajes de error. Puedes ejecutar nuevamente para reintentar.')
    print('SRTM/Geoportal municipal: requieren seleccionar zona y/o acceso; descargar manualmente con el portal oficial.')
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
