"""Pruebas unitarias con embeddings sintéticos (sin pesos ni red)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone

import numpy as np
import pytest

from src.export import COLUMNS, results_to_dataframe, write_csv
from src.gallery import Gallery
from src.matcher import UNKNOWN, cosine_similarity, match
from src.pipeline import FacePipeline, FaceResult


def rnd(seed, dim=512):
    v = np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------- comparador ----------
def test_cosine_identical_and_orthogonal():
    a = rnd(1)
    assert cosine_similarity(a, a) == pytest.approx(1.0, abs=1e-5)
    e1, e2 = np.eye(4, dtype=np.float32)[0], np.eye(4, dtype=np.float32)[1]
    assert cosine_similarity(e1, e2) == pytest.approx(0.0, abs=1e-6)


def test_match_empty_gallery_is_unknown():
    r = match(rnd(1), np.zeros((0, 512), np.float32), [], 0.4)
    assert r.identity == UNKNOWN and np.isnan(r.similarity) and r.best_candidate is None


def test_match_known_identity_above_threshold():
    g = Gallery()
    g.add("ana", rnd(1)); g.add("luis", rnd(2))
    r = match(rnd(1), g.embeddings, g.labels, 0.4)
    assert r.identity == "ana" and r.similarity == pytest.approx(1.0, abs=1e-5)


def test_match_below_threshold_is_unknown_but_reports_candidate():
    g = Gallery()
    g.add("ana", rnd(1))
    r = match(rnd(99), g.embeddings, g.labels, 0.4)  # vectores aleatorios 512-D ~ ortogonales
    assert r.identity == UNKNOWN and r.best_candidate == "ana" and r.similarity < 0.4


def test_match_threshold_configurable_boundary():
    g = Gallery()
    a = rnd(1)
    b = 0.6 * a + 0.8 * rnd(2)  # similitud ~0.6 con a
    g.add("ana", a)
    s = cosine_similarity(a, b)
    assert match(b, g.embeddings, g.labels, s - 0.01).identity == "ana"
    assert match(b, g.embeddings, g.labels, s + 0.01).identity == UNKNOWN


def test_match_uses_max_over_identity_images():
    g = Gallery()
    g.add("ana", rnd(5)); g.add("ana", rnd(1)); g.add("luis", rnd(2))
    assert match(rnd(1), g.embeddings, g.labels, 0.4).identity == "ana"


# ---------- galería ----------
def test_gallery_roundtrip(tmp_path):
    g = Gallery()
    g.add("ana", rnd(1), "a1.jpg"); g.add("luis", rnd(2), "l1.jpg")
    npz, js = g.save(tmp_path / "gal")
    assert npz.exists() and js.exists()
    g2 = Gallery.load(tmp_path / "gal")
    assert g2.labels == ["ana", "luis"] and g2.sources == ["a1.jpg", "l1.jpg"]
    assert np.allclose(g2.embeddings, g.embeddings)
    assert g2.identities == ["ana", "luis"]


def test_gallery_load_missing_returns_empty(tmp_path):
    g = Gallery.load(tmp_path / "no_existe")
    assert len(g) == 0


def test_gallery_rejects_dimension_mismatch():
    g = Gallery()
    g.add("ana", rnd(1, 512))
    with pytest.raises(ValueError):
        g.add("luis", rnd(2, 128))


def test_gallery_corrupt_detected(tmp_path):
    g = Gallery()
    g.add("ana", rnd(1))
    g.save(tmp_path / "gal")
    (tmp_path / "gal.json").write_text('{"labels": ["a", "b"], "sources": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        Gallery.load(tmp_path / "gal")


# ---------- pipeline con detector/embedder falsos ----------
class FakeDet:
    def detect(self, img):
        from src.detector import Detection
        return [Detection((10, 20, 110, 140), 0.99, np.zeros((5, 2), np.float32))]


class FakeEmb:
    def __init__(self, v): self.v = v
    def embed(self, img, lm): return self.v


def test_pipeline_with_fakes():
    g = Gallery(); g.add("ana", rnd(1))
    res = FacePipeline(FakeDet(), FakeEmb(rnd(1)), g, 0.4).process(np.zeros((200, 200, 3), np.uint8))
    assert len(res) == 1 and res[0].match.identity == "ana"
    res = FacePipeline(FakeDet(), FakeEmb(rnd(7)), g, 0.4).process(np.zeros((200, 200, 3), np.uint8))
    assert res[0].match.identity == UNKNOWN
    res = FacePipeline(FakeDet(), FakeEmb(rnd(1)), Gallery(), 0.4).process(np.zeros((200, 200, 3), np.uint8))
    assert res[0].match.identity == UNKNOWN


# ---------- exportación ----------
def test_export_csv_columns_and_values(tmp_path):
    g = Gallery(); g.add("ana", rnd(1))
    res = FacePipeline(FakeDet(), FakeEmb(rnd(1)), g, 0.4).process(np.zeros((200, 200, 3), np.uint8))
    df = results_to_dataframe("foto.jpg", res, now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    path = write_csv(df, tmp_path / "sub" / "out.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == COLUMNS
    r = rows[0]
    assert r["imagen"] == "foto.jpg" and r["indice_rostro"] == "0" and r["identidad"] == "ana"
    assert r["fecha_utc"] == "2026-01-02T03:04:05Z" and float(r["umbral"]) == 0.4
    assert [float(r[k]) for k in ("x1", "y1", "x2", "y2")] == [10.0, 20.0, 110.0, 140.0]


def test_export_empty_gallery_blank_similarity():
    res = FacePipeline(FakeDet(), FakeEmb(rnd(1)), Gallery(), 0.4).process(np.zeros((50, 50, 3), np.uint8))
    df = results_to_dataframe("x.jpg", res)
    assert df.loc[0, "identidad"] == UNKNOWN and df.loc[0, "similitud"] == ""


def test_export_no_faces_header_only(tmp_path):
    df = results_to_dataframe("x.jpg", [])
    p = write_csv(df, tmp_path / "e.csv")
    assert p.read_text(encoding="utf-8").strip() == ",".join(COLUMNS)
