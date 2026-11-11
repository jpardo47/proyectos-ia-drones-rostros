"""Punto de entrada de la demo P3 (investigacion y simulacion; DATOS SIMULADOS).

    python app.py demo [--scenario basico --seed 42]
    python app.py api [--port 8000]
    python app.py dashboard
    python app.py scenarios
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FALLBACK_SCENARIOS = [
    "basico", "sin_remote_id", "duplicados", "contradictorio", "corroborado", "perdida_senal",
    "estacion_caida", "malformados", "sin_estacion_control", "rangos_100m_10km",
]


def _print_summary(s: dict) -> None:
    print("=" * 70)
    print("DATOS SIMULADOS - demostracion de investigacion, no son detecciones reales")
    print("=" * 70)
    print(f"Escenario: {s['scenario']}   Semilla: {s['seed']}")
    if s.get("descripcion"):
        print(f"Descripcion: {s['descripcion']}")
    print(f"Eventos recibidos:        {s['events']}")
    print(f"Observaciones validas:    {s['observaciones_validas']}")
    print(f"Aceptadas por el motor:   {s['accepted']}")
    print(f"Duplicados descartados:   {s['duplicates']}")
    print(f"Rechazados:               {s['rejected']}")
    for code, n in s["rejected_by_code"].items():
        print(f"   - {code}: {n}")
    print(f"Tracks:                   {s['tracks']}")
    print("   Estado final (tras agotar el tiempo de caducidad al terminar el escenario):")
    for state, n in s["tracks_by_state"].items():
        print(f"   - {state}: {n}")
    print("   Estados alcanzados durante el escenario (tracks que pasaron por cada uno):")
    for state, n in s.get("tracks_reached_state", {}).items():
        print(f"   - {state}: {n}")
    print(f"Decisiones:               {s['decisions']}")
    print(f"Alertas informativas:     {s['alerts']} (requieren revision humana)")
    print(f"Base de datos:            {s['db_path']}")
    print("Todos los datos son simulados; los nodos son ficticios.")


def cmd_demo(args: argparse.Namespace) -> int:
    from src.orchestration.runner import run_demo

    try:
        summary = run_demo(args.scenario, args.seed, db_path=args.db, batch_seconds=args.batch_seconds)
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, KeyError) as exc:
        print(f"ERROR: escenario o parametros no validos: {exc}", file=sys.stderr)
        return 2
    _print_summary(summary)
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    print("API de la demo (DATOS SIMULADOS). Escritura protegida: defina POPAYAN_API_TOKEN.")
    uvicorn.run("src.api.main:app", host=args.host, port=args.port)
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    # Solo en la máquina local: sin --server.address Streamlit escucha en todas las interfaces de red.
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(ROOT / "src" / "dashboard" / "app.py"),
        "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false",
        # Sin modo headless, la primera ejecución de Streamlit se detiene a pedir un correo.
        "--server.headless", "true",
    ]
    print("Dashboard de la demo (DATOS SIMULADOS). Abra http://127.0.0.1:8501 en el navegador.")
    return subprocess.call(cmd, cwd=str(ROOT))


def cmd_scenarios(args: argparse.Namespace) -> int:
    try:
        from src.simulation.scenario import list_scenarios

        names = list(list_scenarios())
    except ImportError:
        names = FALLBACK_SCENARIOS
        print("(modulo de simulacion no disponible; lista de referencia)")
    print("Escenarios simulados:")
    for n in names:
        print(f"  - {n}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Demo P3 de localizacion multisensor - DATOS SIMULADOS")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo", help="ejecuta un escenario simulado y resume el resultado")
    d.add_argument("--scenario", default="basico")
    d.add_argument("--seed", type=int, default=42)
    d.add_argument("--batch-seconds", type=float, default=5.0)
    d.add_argument("--db", default=str(ROOT / "data" / "runtime" / "popayan_demo.sqlite"))
    d.set_defaults(func=cmd_demo)
    a = sub.add_parser("api", help="inicia la API (uvicorn)")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=8000)
    a.set_defaults(func=cmd_api)
    sub.add_parser("dashboard", help="inicia el dashboard (streamlit)").set_defaults(func=cmd_dashboard)
    sub.add_parser("scenarios", help="lista los escenarios").set_defaults(func=cmd_scenarios)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
