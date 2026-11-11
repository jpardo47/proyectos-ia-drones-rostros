"""Galería de identidades consentidas: alta desde carpetas, guardado/carga en .npz + JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Gallery:
    embeddings: np.ndarray = field(default_factory=lambda: np.zeros((0, 512), dtype=np.float32))
    labels: list[str] = field(default_factory=list)  # una etiqueta por fila de embeddings
    sources: list[str] = field(default_factory=list)  # nombre de la imagen de origen

    def __len__(self) -> int:
        return len(self.labels)

    @property
    def identities(self) -> list[str]:
        return sorted(set(self.labels))

    def add(self, name: str, embedding: np.ndarray, source: str = "") -> None:
        emb = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        if len(self.labels) and emb.shape[1] != self.embeddings.shape[1]:
            raise ValueError("Dimensión de embedding incompatible con la galería")
        self.embeddings = emb if len(self.labels) == 0 else np.vstack([self.embeddings, emb])
        self.labels.append(name)
        self.sources.append(source)

    def save(self, prefix: str | Path) -> tuple[Path, Path]:
        """Guarda ``<prefix>.npz`` (vectores) y ``<prefix>.json`` (metadatos)."""
        prefix = Path(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        npz, js = prefix.with_suffix(".npz"), prefix.with_suffix(".json")
        np.savez_compressed(npz, embeddings=self.embeddings)
        js.write_text(json.dumps({"labels": self.labels, "sources": self.sources}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        return npz, js

    @classmethod
    def load(cls, prefix: str | Path) -> "Gallery":
        prefix = Path(prefix)
        npz, js = prefix.with_suffix(".npz"), prefix.with_suffix(".json")
        if not npz.exists() or not js.exists():
            return cls()
        meta = json.loads(js.read_text(encoding="utf-8"))
        emb = np.load(npz)["embeddings"].astype(np.float32)
        if len(meta["labels"]) != len(emb):
            raise ValueError("Galería corrupta: etiquetas y embeddings no coinciden")
        return cls(emb, list(meta["labels"]), list(meta.get("sources", [""] * len(emb))))


def enroll_from_folder(folder: str | Path, detector, embedder,
                       gallery: Gallery | None = None) -> tuple[Gallery, list[str]]:
    """Da de alta ``folder/<nombre>/*.jpg``. Usa el rostro más grande de cada imagen.

    Devuelve (galería, avisos) con las imágenes omitidas (ilegibles o sin rostro).
    """
    import cv2

    gallery = gallery or Gallery()
    warnings: list[str] = []
    folder = Path(folder)
    if not folder.exists():
        return gallery, [f"La carpeta {folder} no existe"]
    for person in sorted(p for p in folder.iterdir() if p.is_dir()):
        for img_path in sorted(p for p in person.iterdir() if p.suffix.lower() in IMAGE_EXTS):
            img = cv2.imread(str(img_path))
            if img is None:
                warnings.append(f"{img_path}: no se pudo leer")
                continue
            dets = detector.detect(img)
            if not dets:
                warnings.append(f"{img_path}: sin rostro detectado")
                continue
            best = max(dets, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
            gallery.add(person.name, embedder.embed(img, best.landmarks), img_path.name)
    return gallery, warnings
