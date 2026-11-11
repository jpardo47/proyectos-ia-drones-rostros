"""Construcción del manifiesto de entrenamiento (archivo -> etiqueta -> grabación/grupo).

Las etiquetas NO se suponen: se leen de la carpeta padre o del prefijo del nombre del archivo
(texto antes del primer '_' / '-' / dígito) y se traducen con un mapa explícito
`clase_original -> drone | no_drone`. Las clases sin mapear se excluyen y se informan.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from src.audio.features import FeatureConfig
from src.pipeline import features_for_file

AUDIO_EXT = {".wav", ".flac"}


def source_class(path: Path, root: Path, rule: str) -> str:
    if rule == "folder":
        rel = path.relative_to(root)
        return rel.parts[-2].upper() if len(rel.parts) >= 2 else ""
    if rule == "prefix":
        m = re.match(r"([A-Za-z]+)", path.stem)
        return m.group(1).upper() if m else ""
    raise ValueError(f"regla desconocida: {rule}")


def scan_audio(root: str | Path) -> list[Path]:
    root = Path(root)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXT)


def build_manifest(root: str | Path, label_map: dict[str, str], rule: str = "prefix",
                   group_regex: str | None = None, data_origin: str = "replay") -> tuple[pd.DataFrame, dict]:
    """Devuelve (manifiesto, resumen). group = ruta relativa (1 archivo = 1 grabación) salvo que
    `group_regex` extraiga un identificador de sesión común (grupo 1 de la regex sobre el nombre)."""
    root = Path(root)
    label_map = {k.upper(): v for k, v in label_map.items()}
    rows, excluded = [], Counter()
    for p in scan_audio(root):
        sc = source_class(p, root, rule)
        if sc not in label_map:
            excluded[sc] += 1
            continue
        group = str(p.relative_to(root)).replace("\\", "/")
        if group_regex:
            m = re.search(group_regex, p.name)
            if m:
                group = m.group(1)
        rows.append({"path": str(p), "label": label_map[sc], "source_class": sc, "group": group,
                     "data_origin": data_origin})
    df = pd.DataFrame(rows, columns=["path", "label", "source_class", "group", "data_origin"])
    summary = {
        "root": str(root), "rule": rule, "n_files": int(len(df)),
        "files_per_source_class": {k: int(v) for k, v in df["source_class"].value_counts().sort_index().items()} if len(df) else {},
        "files_per_label": {k: int(v) for k, v in df["label"].value_counts().sort_index().items()} if len(df) else {},
        "groups_per_label": {k: int(v) for k, v in df.groupby("label")["group"].nunique().sort_index().items()} if len(df) else {},
        "excluded_source_classes": dict(excluded),
    }
    return df, summary


def featurize_manifest(df: pd.DataFrame, cfg: FeatureConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    """Extrae features por ventana. Devuelve X, y (1=drone), grupos por ventana e info por archivo."""
    Xs, ys, gs, info = [], [], [], []
    for row in df.itertuples(index=False):
        try:
            X = features_for_file(row.path, cfg)
        except Exception as exc:  # archivo ilegible: se registra y se omite
            info.append({"path": row.path, "error": repr(exc)})
            continue
        Xs.append(X)
        ys.append(np.full(len(X), 1 if row.label == "drone" else 0))
        gs.append(np.array([row.group] * len(X), dtype=object))
        info.append({"path": row.path, "n_windows": int(len(X))})
    if not Xs:
        raise RuntimeError("no se pudo extraer ninguna feature")
    return np.vstack(Xs), np.concatenate(ys), np.concatenate(gs), info
