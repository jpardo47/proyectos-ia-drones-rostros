"""Exportación de resultados a CSV."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

COLUMNS = ["imagen", "indice_rostro", "x1", "y1", "x2", "y2", "puntuacion_deteccion",
           "identidad", "similitud", "umbral", "fecha_utc"]


def results_to_dataframe(image_name: str, results, now: datetime | None = None) -> pd.DataFrame:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for r in results:
        x1, y1, x2, y2 = r.bbox
        sim = r.match.similarity
        rows.append({
            "imagen": image_name, "indice_rostro": r.index,
            "x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1),
            "puntuacion_deteccion": round(r.detection_score, 4),
            "identidad": r.match.identity,
            "similitud": "" if sim != sim else round(float(sim), 4),  # nan -> vacío
            "umbral": r.match.threshold, "fecha_utc": stamp,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return path
