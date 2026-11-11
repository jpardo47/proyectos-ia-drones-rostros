#!/usr/bin/env python3
"""Descarga de datasets públicos para los proyectos IA (solo biblioteca estándar).

Ejemplos:
  python descargar_datasets.py                      # igual que --basicos (LFW + audio de drones)
  python descargar_datasets.py --basicos
  python descargar_datasets.py --lfw --extraer
  python descargar_datasets.py --audio --muestra-audio 10
  python descargar_datasets.py --todos --permitir-grandes
  python descargar_datasets.py --verificar          # solo URLs, tamaños y disponibilidad; no descarga

Destino por defecto: la carpeta padre de este kit (la raíz del proyecto). Se puede cambiar con --dest.
Registro persistente: kit_descarga_datasets/estado_descargas.json
Manifiesto final:     kit_descarga_datasets/descargas_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parent
ROOT_DEFAULT = KIT.parent
REGISTRO = KIT / "estado_descargas.json"
MANIFIESTO = KIT / "descargas_manifest.json"

LIMITE_BYTES = 500 * 1024 * 1024        # descargas por encima de esto requieren --permitir-grandes
MARGEN_DISCO = 1024 * 1024 * 1024       # espacio libre adicional exigido
MAX_INTENTOS = 3                         # reintentos por archivo (espera 5 s, 10 s)
TIMEOUT = 60
CHUNK = 1024 * 1024
PERIODO_REGISTRO = 3.0                   # segundos entre actualizaciones del registro
USER_AGENT = "DatasetPreparation/1.0 (educational research; data download)"

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
EXT_AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff", ".aif"}

PROY_LFW = "demo-reconocimiento-facial-uniface"
PROY_AUDIO = "demo-deteccion-drones-audio"
PROY_MAPA = "demo-localizacion-drones-popayan"

LIC_LFW = "Uso de investigación (LFW, UMass); licencia formal no verificada en esta sesión"
LIC_AUDIO = "CC0-1.0 (verificada en la API de GitHub y en el LICENSE del repositorio)"
LIC_OSM = "ODbL (OpenStreetMap; Geofabrik)"
LIC_NASA = "PENDIENTE (licencia por confirmar)"


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mib(n: float | int | None) -> str:
    return "?" if n is None else f"{n / (1024 ** 2):.1f}"


# ---------------------------------------------------------------- registro

def leer_registro() -> dict:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"archivos": {}}


def escribir_json_atomico(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Nombre temporal propio de cada proceso: dos descargas pueden escribir el registro a la vez.
    tmp = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    for _ in range(20):
        try:
            os.replace(tmp, ruta)
            return
        except PermissionError:  # el monitor puede tener el archivo abierto en Windows
            time.sleep(0.2)
    raise PermissionError(f"No se pudo reemplazar {ruta}")


def actualizar(clave: str, **campos) -> None:
    """Actualiza el registro. Un fallo al escribirlo no detiene la descarga (el archivo es la verdad)."""
    try:
        reg = leer_registro()
        entrada = reg.setdefault("archivos", {}).setdefault(clave, {})
        entrada.update(campos)
        entrada["fecha_utc"] = ahora()
        reg["actualizado_utc"] = ahora()
        escribir_json_atomico(REGISTRO, reg)
    except OSError as exc:
        print(f"[AVISO] No se pudo escribir el registro ({type(exc).__name__}: {exc}); se reintentará al siguiente cambio.", flush=True)


def meta(it: dict) -> dict:
    return {"dataset": it["dataset"], "proyecto": it["proyecto"], "licencia": it["licencia"],
            "url": it["url"], "destino": it["destino"], "sha256_oficial": it["sha256_oficial"],
            "nota": it["nota"]}


# ---------------------------------------------------------------- HTTP y hashes

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for bloque in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def peticion(url: str, inicio: int = 0, primer_byte: bool = False) -> urllib.request.Request:
    cab = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if primer_byte:
        cab["Range"] = "bytes=0-0"
    elif inicio:
        cab["Range"] = f"bytes={inicio}-"
    return urllib.request.Request(url, headers=cab)


def comprobar_url(url: str) -> dict:
    """GET con 'Range: bytes=0-0' (HEAD no sirve: Figshare y NASA devuelven 403 a HEAD)."""
    try:
        with urllib.request.urlopen(peticion(url, primer_byte=True), timeout=TIMEOUT) as r:
            codigo = r.status
            total = None
            if codigo == 206:
                rango = r.headers.get("Content-Range", "")  # p. ej. "bytes 0-0/243346528"
                total = int(rango.rsplit("/", 1)[1]) if "/" in rango else None
            elif codigo == 200:
                cl = r.headers.get("Content-Length")
                total = int(cl) if cl else None
            return {"http": codigo, "bytes": total, "rangos": codigo == 206, "error": None}
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, "bytes": None, "rangos": False, "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # red, DNS, timeout, formato inesperado
        return {"http": None, "bytes": None, "rangos": False, "error": f"{type(exc).__name__}: {exc}"}


def obtener_json(url: str):
    with urllib.request.urlopen(peticion(url), timeout=TIMEOUT) as r:
        return json.load(r)


def arbol_audio() -> list[tuple[str, int]]:
    """Lista (ruta, tamaño) de las grabaciones de audio del repositorio, sin videos."""
    arbol = obtener_json(GITHUB_TREE)
    if arbol.get("truncated"):
        print("[AVISO] Árbol de GitHub truncado; puede faltar parte de los archivos.")
    filas = sorted(
        (r["path"], int(r.get("size") or 0))
        for r in arbol.get("tree", [])
        if r.get("type") == "blob"
        and Path(r["path"]).suffix.lower() in EXT_AUDIO
        and "audio" in [p.lower() for p in Path(r["path"]).parts]
    )
    if not filas:
        raise RuntimeError("No se encontraron grabaciones en carpetas Audio.")
    return filas


# ---------------------------------------------------------------- catálogo

def item(base: Path, grupo: str, nombre: str, proyecto: str, licencia: str, url: str,
         destino: Path, sha: str | None = None, tamano: int | None = None,
         nota: str = "", omitir: bool = False, pendiente: bool = False) -> dict:
    return {"grupo": grupo, "dataset": nombre, "proyecto": proyecto, "licencia": licencia,
            "url": url, "destino": str(destino), "clave": destino.relative_to(base).as_posix(),
            "sha256_oficial": sha, "tamano_tabla": tamano, "nota": nota,
            "omitir": omitir, "pendiente": pendiente}


def catalogo(base: Path, audio: list[tuple[str, int]]) -> list[dict]:
    lfw_dir = base / PROY_LFW / "data" / "raw" / "lfw"
    items = [item(base, "lfw", "LFW funneled (lfw-funneled.tgz)", PROY_LFW, LIC_LFW,
                  LFW_URL, lfw_dir / "lfw-funneled.tgz", LFW_SHA256)]
    for nombre, (url, sha) in LFW_PAIRS.items():
        items.append(item(base, "lfw", f"LFW pares de evaluación ({nombre})", PROY_LFW, LIC_LFW,
                          url, lfw_dir / nombre, sha))
    audio_dir = base / PROY_AUDIO / "data" / "raw" / "DroneDetectionThesis"
    for ruta, tam in audio:
        items.append(item(base, "audio", "Drone detection: audio WAV", PROY_AUDIO, LIC_AUDIO,
                          RAW_BASE + urllib.parse.quote(ruta, safe="/"),
                          audio_dir / Path(ruta), None, tam))
    items.append(item(base, "osm", "OpenStreetMap Colombia (Geofabrik) PBF", PROY_MAPA, LIC_OSM,
                      OSM_URL, base / PROY_MAPA / "data" / "raw" / "colombia-latest.osm.pbf",
                      pendiente=True,
                      nota="PENDIENTE: no necesario, el dashboard usa teselas publicas. Solo se registra."))
    items.append(item(base, "nasa", "NASA small UAV acoustics", PROY_AUDIO, LIC_NASA,
                      NASA_URL, base / PROY_AUDIO / "data" / "raw" / "nasa_small_uav_acoustics.zip",
                      omitir=True, nota="No descargado: licencia no especificada."))
    return items


# ---------------------------------------------------------------- descarga

def ya_completo(dest: Path, esperados: int | None, sha: str | None) -> tuple[bool, str | None]:
    if not dest.is_file() or esperados is None or dest.stat().st_size != esperados:
        return False, None
    digest = sha256_file(dest)
    if sha and digest != sha:
        return False, digest
    return True, digest


def descargar_archivo(it: dict, esperados: int | None) -> bool:
    clave, dest = it["clave"], Path(it["destino"])
    tmp = dest.with_name(dest.name + ".parcial")
    dest.parent.mkdir(parents=True, exist_ok=True)
    actualizar(clave, **meta(it), estado="pendiente", bytes_esperados=esperados)
    for intento in range(1, MAX_INTENTOS + 1):
        inicio = tmp.stat().st_size if tmp.is_file() else 0
        if esperados and inicio > esperados:
            tmp.unlink()
            inicio = 0
        actualizar(clave, estado="descargando", intentos=intento, bytes_actuales=inicio, pid=os.getpid())
        print(f"[DESCARGANDO] {dest.name} (intento {intento}/{MAX_INTENTOS}, desde {mib(inicio)} MiB)", flush=True)
        try:
            with urllib.request.urlopen(peticion(it["url"], inicio), timeout=TIMEOUT) as resp:
                if inicio and resp.status == 206:
                    modo, base_bytes = "ab", inicio          # reanudación confirmada
                else:
                    if inicio:
                        print("[AVISO] El servidor no admite reanudar; se descarga desde cero.")
                    modo, base_bytes = "wb", 0
                escritos, ultimo = 0, time.monotonic()
                with tmp.open(modo) as salida:
                    while True:
                        bloque = resp.read(CHUNK)
                        if not bloque:
                            break
                        salida.write(bloque)
                        escritos += len(bloque)
                        if time.monotonic() - ultimo >= PERIODO_REGISTRO:
                            actualizar(clave, bytes_actuales=base_bytes + escritos, estado="descargando", pid=os.getpid())
                            print(f"    {mib(base_bytes + escritos)} MiB" + (f" / {mib(esperados)} MiB" if esperados else ""), flush=True)
                            ultimo = time.monotonic()
            tamano = tmp.stat().st_size
            if esperados and tamano != esperados:
                raise RuntimeError(f"tamaño {tamano} distinto del esperado {esperados}")
            digest = sha256_file(tmp)
            if it["sha256_oficial"] and digest != it["sha256_oficial"]:
                tmp.unlink()
                raise ValueError("SHA256 no coincide con el oficial; parcial descartado")
            os.replace(tmp, dest)
            actualizar(clave, estado="completo", bytes_actuales=tamano, sha256=digest, ultimo_error=None, pid=None)
            print(f"[OK] {dest.name}: {mib(tamano)} MiB, sha256 {digest[:12]}...", flush=True)
            return True
        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code} {exc.reason}"
            if exc.code == 416 and tmp.is_file():  # rango no válido: empezar de nuevo
                tmp.unlink()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        actualizar(clave, ultimo_error=error, bytes_actuales=tmp.stat().st_size if tmp.is_file() else 0)
        print(f"[ERROR] {dest.name}: {error}", flush=True)
        if intento < MAX_INTENTOS:
            time.sleep(5 * intento)
    actualizar(clave, estado="fallido", pid=None)
    return False


def extraer_seguro(archivo: Path, destino: Path) -> int:
    """Extrae un .tgz validando TODAS las entradas antes de escribir nada."""
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    with tarfile.open(archivo, "r:gz") as tar:
        miembros = tar.getmembers()
        for m in miembros:
            if not (m.isfile() or m.isdir()):
                raise ValueError(f"Entrada no permitida (enlace o dispositivo): {m.name}")
            ruta = Path(m.name)
            if ruta.is_absolute() or ruta.drive or ".." in ruta.parts:
                raise ValueError(f"Ruta insegura en el archivo: {m.name}")
            final = (raiz / ruta).resolve()
            if final != raiz and raiz not in final.parents:
                raise ValueError(f"La ruta sale del destino: {m.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(raiz, members=miembros, filter="data")
        else:  # Python 3.11.0-3.11.3 sin filtro 'data'; la validación previa cubre el caso
            tar.extractall(raiz, members=miembros)
    return len(miembros)


def escribir_manifiesto(items: list[dict], base: Path, modo: str) -> None:
    reg = leer_registro().get("archivos", {})
    filas = []
    for it in items:
        fila = {"clave": it["clave"], "grupo": it["grupo"]}
        fila.update(reg.get(it["clave"], {}))
        filas.append(fila)
    escribir_json_atomico(MANIFIESTO, {"generado_utc": ahora(), "modo": modo,
                                       "destino": str(base), "archivos": filas})


# ---------------------------------------------------------------- modos

def modo_verificar(items: list[dict]) -> int:
    print("[VERIFICAR] Solo se comprueban URLs, tamaños y disponibilidad. No se descarga nada.")
    fallos = 0
    for it in items:
        dest = Path(it["destino"])
        if it["omitir"] or it["pendiente"]:
            res = comprobar_url(it["url"])
            estado = "omitido" if it["omitir"] else "pendiente"
            esperados = res["bytes"]
            actualizar(it["clave"], **meta(it), http_estado=res["http"], rangos=res["rangos"],
                       bytes_esperados=esperados, estado=estado,
                       ultimo_error=res["error"], modo="verificar")
            print(f"[{estado.upper()}] {it['dataset']}: HTTP {res['http']}, {mib(esperados)} MiB. {it['nota']}")
            continue
        res = comprobar_url(it["url"])
        esperados = it["tamano_tabla"] or res["bytes"]
        ok_http = res["http"] in (200, 206)
        sha_local = None
        if dest.is_file() and esperados and dest.stat().st_size == esperados:
            completo, sha_local = ya_completo(dest, esperados, it["sha256_oficial"])
            estado = "completo" if completo else "fallido"
            error = None if completo else "SHA256 local distinto del oficial"
        else:
            estado = "pendiente" if ok_http else "fallido"
            error = res["error"]
        if estado == "fallido":
            fallos += 1
        actualizar(it["clave"], **meta(it), http_estado=res["http"], rangos=res["rangos"],
                   bytes_esperados=esperados, bytes_actuales=dest.stat().st_size if dest.is_file() else 0,
                   estado=estado, sha256=sha_local, ultimo_error=error, modo="verificar")
        if it["grupo"] != "audio":  # el audio son muchas líneas: se resume al final
            print(f"[{estado.upper()}] {dest.name}: HTTP {res['http']}, {mib(esperados)} MiB, rangos={res['rangos']}")
    audio = [it for it in items if it["grupo"] == "audio"]
    if audio:
        ok = sum(1 for it in audio if leer_registro()["archivos"].get(it["clave"], {}).get("http_estado") in (200, 206))
        tot = sum(it["tamano_tabla"] or 0 for it in audio)
        print(f"[AUDIO] {len(audio)} grabaciones, {mib(tot)} MiB en total; disponibles: {ok}/{len(audio)}.")
    return fallos


def modo_descarga(items: list[dict], base: Path, permitir_grandes: bool) -> int:
    pendientes: list[tuple[dict, int | None]] = []
    for it in items:
        if it["omitir"]:
            actualizar(it["clave"], **meta(it), estado="omitido", ultimo_error=it["nota"])
            print(f"[OMITIDO] {it['dataset']}: {it['nota']}")
            continue
        dest = Path(it["destino"])
        if it["grupo"] == "audio":
            esperados = it["tamano_tabla"]
        else:
            res = comprobar_url(it["url"])
            if res["http"] not in (200, 206):
                actualizar(it["clave"], **meta(it), estado="fallido", ultimo_error=res["error"], http_estado=res["http"])
                print(f"[FALLIDO] {dest.name}: {res['error']}")
                continue
            esperados = res["bytes"]
            actualizar(it["clave"], **meta(it), http_estado=res["http"], rangos=res["rangos"], bytes_esperados=esperados)
        completo, sha = ya_completo(dest, esperados, it["sha256_oficial"])
        if completo:
            actualizar(it["clave"], **meta(it), estado="completo", bytes_actuales=esperados, sha256=sha, ultimo_error=None, pid=None)
            print(f"[YA EXISTE Y VERIFICADO] {dest.name}")
            continue
        pendientes.append((it, esperados))

    if pendientes:
        tmp_bytes = lambda it: (Path(it["destino"]).with_name(Path(it["destino"]).name + ".parcial").stat().st_size
                                if Path(it["destino"]).with_name(Path(it["destino"]).name + ".parcial").is_file() else 0)
        faltan = sum(max(0, (e or 0) - tmp_bytes(it)) for it, e in pendientes)
        print(f"[PLAN] {len(pendientes)} archivos por descargar, {mib(faltan)} MiB restantes en total.")
        if faltan > LIMITE_BYTES and not permitir_grandes:
            msg = "Lote superior a 500 MB: no se descarga. Usa --muestra-audio N o --permitir-grandes."
            print(f"[NEGADO] {msg}")
            for it, _ in pendientes:
                actualizar(it["clave"], **meta(it), estado="omitido", ultimo_error=msg)
            return 2
        libre = shutil.disk_usage(base).free
        if faltan + MARGEN_DISCO > libre:
            print(f"[NEGADO] Espacio libre insuficiente: {mib(libre)} MiB disponibles, se necesitan {mib(faltan + MARGEN_DISCO)} MiB.")
            return 3
        for it, esperados in pendientes:
            descargar_archivo(it, esperados)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Descarga datasets públicos para los proyectos IA.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--basicos", action="store_true", help="LFW y audio de drones (por defecto).")
    g.add_argument("--todos", action="store_true", help="LFW, audio y OSM Colombia (OSM ~334 MB; usa --permitir-grandes).")
    g.add_argument("--lfw", action="store_true", help="Solo LFW.")
    g.add_argument("--audio", action="store_true", help="Solo audio de drones.")
    g.add_argument("--osm", action="store_true", help="Solo cartografía Colombia (~334 MB).")
    g.add_argument("--nasa", action="store_true", help="NASA: NO se descarga (licencia no especificada); solo se registra.")
    p.add_argument("--verificar", action="store_true", help="Solo comprueba URLs, tamaños y disponibilidad; no descarga.")
    p.add_argument("--extraer", action="store_true", help="Tras descargar LFW, extrae lfw-funneled.tgz de forma segura.")
    p.add_argument("--permitir-grandes", action="store_true", help="Permite lotes de más de 500 MB.")
    p.add_argument("--muestra-audio", type=int, default=0, help="Descarga solo los primeros N audios (0 = todos).")
    p.add_argument("--dest", type=Path, default=ROOT_DEFAULT, help="Carpeta raíz de destino (por defecto, la del proyecto).")
    args = p.parse_args()

    base = args.dest.expanduser().resolve()
    print(f"[DESTINO] {base}")
    print(f"[REGISTRO] {REGISTRO}")

    if args.todos:
        sel = {"lfw", "audio", "osm"}
    elif args.basicos:
        sel = {"lfw", "audio"}
    else:
        sel = {g for g in ("lfw", "audio", "osm", "nasa") if getattr(args, g)} or {"lfw", "audio"}
    if args.verificar:
        sel = {"lfw", "audio", "osm", "nasa"}

    audio: list[tuple[str, int]] = []
    if "audio" in sel or args.verificar:
        try:
            audio = arbol_audio()
            print(f"[INFO] Grabaciones de audio en el repositorio: {len(audio)} ({mib(sum(t for _, t in audio))} MiB).")
        except Exception as exc:
            print(f"[ERROR] No se pudo listar el audio: {exc}")
            if "audio" in sel and not args.verificar:
                return 1
        if args.muestra_audio and not args.verificar:
            audio = audio[: args.muestra_audio]

    items = catalogo(base, audio)
    if not args.verificar:
        items = [it for it in items if it["grupo"] in sel]
    if args.verificar:
        codigo = 1 if modo_verificar(items) else 0
        escribir_manifiesto(items, base, "verificar")
        print(f"[MANIFIESTO] {MANIFIESTO}")
        return codigo

    codigo = modo_descarga(items, base, args.permitir_grandes)

    if args.extraer and "lfw" in sel:
        lfw_tgz = base / PROY_LFW / "data" / "raw" / "lfw" / "lfw-funneled.tgz"
        if lfw_tgz.is_file() and actualizar_estado_completo(lfw_tgz, items):
            try:
                n = extraer_seguro(lfw_tgz, lfw_tgz.parent)
                print(f"[EXTRAIDO] {n} entradas en {lfw_tgz.parent}")
            except Exception as exc:
                print(f"[ERROR] Extracción LFW: {type(exc).__name__}: {exc}")
                codigo = 1
        else:
            print("[AVISO] --extraer: lfw-funneled.tgz no está completo; no se extrae.")

    escribir_manifiesto(items, base, "descarga")
    fallidos = [it["dataset"] for it in items if leer_registro()["archivos"].get(it["clave"], {}).get("estado") == "fallido"]
    print(f"\n[RESUMEN] Fallidos: {len(fallidos)}. Registro: {REGISTRO}. Manifiesto: {MANIFIESTO}")
    print("SRTM y el Geoportal municipal requieren selección manual: ver INSTRUCCIONES.md.")
    return codigo or (1 if fallidos else 0)


def actualizar_estado_completo(ruta: Path, items: list[dict]) -> bool:
    it = next((i for i in items if Path(i["destino"]) == ruta), None)
    return bool(it) and leer_registro()["archivos"].get(it["clave"], {}).get("estado") == "completo"


if __name__ == "__main__":
    sys.exit(main())
