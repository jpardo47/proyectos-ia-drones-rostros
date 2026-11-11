"""Carga de los siete nodos FICTICIOS por defecto.

Datos: ``data/stations/estaciones_ficticias.json`` (propiedad del coordinador).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .domain import Station

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIONS_FILE = PROJECT_ROOT / "data" / "stations" / "estaciones_ficticias.json"

# Punto público de referencia para centrar el mapa (plaza principal, Parque Caldas).
# Solo sirve para encuadrar la cartografía pública; no es una estación.
POPAYAN_REFERENCE = {"name": "Parque Caldas (referencia pública)", "latitude": 2.4419, "longitude": -76.6063}


def load_default_stations(path: Optional[Path] = None) -> list[Station]:
    """Devuelve los 7 nodos ficticios (5 civiles + 2 institucionales abstractos)."""
    source = Path(path) if path else DEFAULT_STATIONS_FILE
    data = json.loads(source.read_text(encoding="utf-8"))
    return [Station.model_validate(item) for item in data["stations"]]
