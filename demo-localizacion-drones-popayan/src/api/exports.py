"""Exportaciones CSV / GeoJSON (compartidas por la API y el dashboard).

Todo dato simulado se marca: columna ``aviso`` en CSV y propiedad ``disclaimer``
("DATOS SIMULADOS") en GeoJSON. Los nodos ``INST-SIM-*`` no tienen geometria.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Mapping, Optional

from src.contracts import DecisionRecord, Observation, Station, Track

DISCLAIMER = "DATOS SIMULADOS"
OBSERVATION_COLUMNS = [
    "event_id", "station_id", "sensor_type", "timestamp_utc", "data_origin", "is_simulated",
    "object_id", "classification", "classifier_score", "latitude", "longitude", "altitude",
    "altitude_reference", "measurement_uncertainty", "sensor_quality", "raw_reference",
]


def _safe_cell(value: Any) -> Any:
    """Evita inyeccion de formulas al abrir el CSV en una hoja de calculo."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def observations_csv(observations: Iterable[Observation]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(OBSERVATION_COLUMNS + ["aviso"])
    for o in observations:
        d = o.model_dump(mode="json")
        row = [_safe_cell("" if d[c] is None else d[c]) for c in OBSERVATION_COLUMNS]
        row.append(DISCLAIMER if o.is_simulated else "")
        writer.writerow(row)
    return buf.getvalue()


def tracks_geojson(
    tracks: Iterable[Track], latest_decisions: Optional[Mapping[str, DecisionRecord]] = None
) -> dict[str, Any]:
    latest = latest_decisions or {}
    features: list[dict[str, Any]] = []
    any_sim = False
    for t in tracks:
        if not t.points:
            continue
        coords = [[p.longitude, p.latitude] for p in t.points]
        geometry = (
            {"type": "LineString", "coordinates": coords}
            if len(coords) >= 2
            else {"type": "Point", "coordinates": coords[0]}
        )
        d = latest.get(t.track_id)
        props: dict[str, Any] = {
            "track_id": t.track_id,
            "object_id": t.object_id,
            "state": d.state.value if d else None,
            "rule_id": d.rule_id if d else None,
            "reason": d.reason if d else None,
            "requires_human_review": d.requires_human_review if d else None,
            "is_lost": t.is_lost,
            "is_simulated": t.is_simulated,
            "first_seen_utc": t.first_seen_utc.isoformat(),
            "last_seen_utc": t.last_seen_utc.isoformat(),
            "n_points": len(t.points),
            "station_ids": list(t.station_ids),
            "sensor_types": [s.value for s in t.sensor_types],
            "position_kind": "posicion reportada (no verificada)",
        }
        if t.is_simulated:
            props["disclaimer"] = DISCLAIMER
            any_sim = True
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if any_sim or not features:
        fc["disclaimer"] = DISCLAIMER
    return fc


def stations_geojson(stations: Iterable[Station]) -> dict[str, Any]:
    features = []
    for s in stations:
        if not s.has_location:  # nodos institucionales abstractos: sin geometria
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s.longitude, s.latitude]},
            "properties": {
                "station_id": s.station_id,
                "name": s.name,
                "category": s.category.value,
                "status": s.status.value,
                "virtual_sensors": [v.value for v in s.virtual_sensors],
                "is_fictitious": s.is_fictitious,
                "disclaimer": "ESTACION FICTICIA - " + DISCLAIMER,
            },
        })
    return {"type": "FeatureCollection", "features": features, "disclaimer": "ESTACIONES FICTICIAS - " + DISCLAIMER}
