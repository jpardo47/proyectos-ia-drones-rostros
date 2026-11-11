#!/usr/bin/env python3
"""Monitor independiente de descargas (solo biblioteca estándar).

Lee estado_descargas.json, mide los *.parcial en disco y escribe una línea de progreso
con fecha en logs/descargas/monitor.log y en consola.

Uso:
  python monitor_descargas.py                  # cada 15 s hasta que no queden descargas activas
  python monitor_descargas.py --intervalo 5
  python monitor_descargas.py --una-vez        # imprime el estado actual y sale
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parent
ROOT = KIT.parent
REGISTRO = KIT / "estado_descargas.json"
LOG = ROOT / "logs" / "descargas" / "monitor.log"


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mib(n) -> str:
    return "?" if n is None else f"{n / (1024 ** 2):.1f}"


def proceso_vivo(pid) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":  # en Windows os.kill(pid, 0) enviaría Ctrl+C: usar tasklist
            salida = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                                    capture_output=True, text=True, timeout=10).stdout
            return str(int(pid)) in salida
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def leer_registro() -> dict | None:
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


def estado_actual() -> dict:
    reg = leer_registro()
    if reg is None:
        return {"sin_registro": True, "activas": [], "contadores": {}, "lineas": []}
    contadores: dict[str, int] = {}
    activas, lineas = [], []
    for clave, e in reg.get("archivos", {}).items():
        est = e.get("estado", "desconocido")
        contadores[est] = contadores.get(est, 0) + 1
        if est != "descargando":
            continue
        dest = Path(e.get("destino", ""))
        parcial = dest.with_name(dest.name + ".parcial")
        medido = parcial.stat().st_size if parcial.is_file() else (dest.stat().st_size if dest.is_file() else 0)
        esperados = e.get("bytes_esperados")
        vivo = proceso_vivo(e.get("pid"))
        pct = f"{100 * medido / esperados:.0f}%" if esperados else "?"
        marca = "" if vivo else " [PROCESO NO ACTIVO: posible interrupcion]"
        linea = f"{dest.name} {mib(medido)}/{mib(esperados)} MiB ({pct}) pid={e.get('pid')}{marca}"
        lineas.append(linea)
        if vivo:
            activas.append(clave)
    return {"sin_registro": False, "activas": activas, "contadores": contadores,
            "lineas": lineas, "actualizado_registro": reg.get("actualizado_utc")}


def formatear(estado: dict) -> str:
    if estado["sin_registro"]:
        return f"{ahora()} | sin registro todavia ({REGISTRO.name})"
    c = estado["contadores"]
    resumen = " ".join(f"{k}={v}" for k, v in sorted(c.items())) or "vacio"
    detalle = " | ".join(estado["lineas"]) if estado["lineas"] else "sin descargas en curso"
    return f"{ahora()} | activas={len(estado['activas'])} | {resumen} | {detalle}"


def escribir(linea: str) -> None:
    print(linea, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Monitor de descargas de datasets.")
    p.add_argument("--intervalo", type=float, default=15.0, help="Segundos entre lecturas (por defecto 15).")
    p.add_argument("--una-vez", action="store_true", help="Imprime el estado actual y sale.")
    args = p.parse_args()

    if args.una_vez:
        escribir(formatear(estado_actual()))
        return 0
    while True:
        est = estado_actual()
        escribir(formatear(est))
        if not est["sin_registro"] and not est["activas"]:
            escribir(f"{ahora()} | no quedan descargas activas; monitor finalizado")
            return 0
        time.sleep(max(1.0, args.intervalo))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
