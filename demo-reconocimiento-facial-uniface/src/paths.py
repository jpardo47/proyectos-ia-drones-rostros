"""Rutas del proyecto y caché de pesos de UniFace (dentro de ``modelos/``)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "modelos"
DEFAULT_GALLERY = ROOT / "datasets" / "galeria"
SAMPLES_DIR = ROOT / "datasets" / "muestras"
RESULTS_DIR = ROOT / "resultados"
GALLERY_STORE = ROOT / "datasets" / "galeria_embeddings"  # prefijo de .npz/.json


def setup_model_cache() -> Path:
    """Apunta la caché de pesos de UniFace a ``modelos/`` (salvo que el usuario ya fije UNIFACE_CACHE_DIR)."""
    os.environ.setdefault("UNIFACE_CACHE_DIR", str(MODELS_DIR))
    return Path(os.environ["UNIFACE_CACHE_DIR"])
