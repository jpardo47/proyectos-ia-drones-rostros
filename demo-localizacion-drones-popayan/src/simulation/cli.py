"""CLI del simulador: ``python -m src.simulation.cli --scenario basico --seed 42 --out ...``."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .scenario import get_scenario, list_scenarios, run_scenario


def _sensor_label(ev) -> str:
    if ev.kind == "remote_id":
        return "remote_id"
    st = ev.payload.get("sensor_type") if isinstance(ev.payload, dict) else None
    return str(st) if isinstance(st, str) else "desconocido"


def summarize(result) -> str:
    by_kind = Counter(ev.kind for ev in result.raw_events)
    by_sensor = Counter(_sensor_label(ev) for ev in result.raw_events)
    by_station = Counter(ev.station_id for ev in result.raw_events)
    drones = sorted({t.drone_id for t in result.truth})
    lines = [
        "=" * 64,
        "DATOS SIMULADOS - Proyecto 3 (no son datos reales ni de sensores)",
        "=" * 64,
        f"Escenario : {result.scenario_id}   (semilla {result.seed})",
        f"Descripcion: {result.description}",
        f"Intervalo : {result.start_utc.isoformat()} -> {result.end_utc.isoformat()}",
        f"Drones virtuales: {len(drones)} ({', '.join(drones)})",
        f"Estaciones: {len(result.stations)}",
    ]
    for s in result.stations:
        loc = f"{s.latitude:.4f},{s.longitude:.4f}" if s.has_location else "sin coordenadas (nodo logico)"
        lines.append(f"  - {s.station_id:<12} {s.status.value:<8} {loc}")
    lines.append(f"Estados verdaderos (truth): {len(result.truth)}   [separados de los eventos]")
    lines.append(f"Eventos crudos: {len(result.raw_events)}")
    lines.append("  por tipo (kind): " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    lines.append("  por sensor     : " + ", ".join(f"{k}={v}" for k, v in sorted(by_sensor.items())))
    lines.append("  por estacion   : " + ", ".join(f"{k}={v}" for k, v in sorted(by_station.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="python -m src.simulation.cli", description="Simulador multisensor (DATOS SIMULADOS)")
    p.add_argument("--scenario", default="basico", help="nombre del escenario")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--duration", type=int, default=None, help="duracion en segundos (opcional)")
    p.add_argument("--out", type=Path, default=None, help="archivo JSON de salida")
    p.add_argument("--list", action="store_true", help="lista los escenarios disponibles")
    args = p.parse_args(argv)

    if args.list:
        print("Escenarios disponibles (DATOS SIMULADOS):")
        for name in list_scenarios():
            print(f"  - {name:<22} {get_scenario(name).description}")
        return 0

    try:
        cfg = get_scenario(args.scenario, args.seed)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.duration:
        cfg = cfg.model_copy(update={"duration_s": args.duration})
    result = run_scenario(cfg)
    print(summarize(result))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
        print(f"JSON escrito en: {args.out}  ({args.out.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
