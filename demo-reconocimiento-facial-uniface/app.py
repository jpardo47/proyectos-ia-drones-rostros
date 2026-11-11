"""Interfaz Streamlit: subir foto autorizada -> cajas, coincidencias, CSV.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import streamlit as st  # noqa: E402

from src.export import results_to_dataframe  # noqa: E402
from src.matcher import DEFAULT_THRESHOLD  # noqa: E402
from src.paths import DEFAULT_GALLERY, GALLERY_STORE  # noqa: E402

st.set_page_config(page_title="Demo reconocimiento facial (UniFace)", layout="wide")
st.title("Demo de reconocimiento facial con UniFace")
st.warning(
    "Uso responsable: suba solo fotografías de personas que hayan dado su consentimiento o de "
    "datasets públicos de investigación. No se guardan las fotos subidas. Es una demo de visión "
    "por computador: sus resultados no son una identificación fiable ni deben usarse para "
    "tomar decisiones sobre personas."
)


@st.cache_resource(show_spinner="Cargando modelos (la primera vez se descargan los pesos)...")
def load_models():
    from src.detector import FaceDetector
    from src.embedder import FaceEmbedder

    return FaceDetector(), FaceEmbedder()


@st.cache_resource(show_spinner="Dando de alta la galería...")
def load_gallery(folder: str):
    from src.gallery import enroll_from_folder

    det, emb = load_models()
    gal, warns = enroll_from_folder(folder, det, emb)
    if len(gal):
        gal.save(GALLERY_STORE)
    return gal, warns


with st.sidebar:
    threshold = st.slider("Umbral de similitud coseno", 0.0, 1.0, DEFAULT_THRESHOLD, 0.01,
                          help="Por debajo del umbral el resultado es 'desconocido'.")
    gallery_dir = st.text_input("Carpeta de galería (galeria/<nombre>/*.jpg)", str(DEFAULT_GALLERY))
    if st.button("Recargar galería"):
        load_gallery.clear()

detector, embedder = load_models()
gallery, warns = load_gallery(gallery_dir)
st.sidebar.write(f"Galería: {len(gallery)} imágenes, {len(gallery.identities)} identidades")
for w in warns:
    st.sidebar.caption(f"Aviso: {w}")

upload = st.file_uploader("Fotografía autorizada", type=["jpg", "jpeg", "png", "bmp", "webp"])
if upload is not None:
    img = cv2.imdecode(np.frombuffer(upload.getvalue(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        st.error("No se pudo leer la imagen.")
    else:
        from src.pipeline import FacePipeline, draw_results

        results = FacePipeline(detector, embedder, gallery, threshold).process(img, threshold)
        c1, c2 = st.columns([3, 2])
        c1.image(cv2.cvtColor(draw_results(img, results), cv2.COLOR_BGR2RGB),
                 caption=f"{len(results)} rostro(s) detectado(s)")
        df = results_to_dataframe(upload.name, results)
        c2.dataframe(df, use_container_width=True)
        c2.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                           file_name="resultados_rostros.csv", mime="text/csv")
        if len(gallery) == 0:
            st.info("La galería está vacía: todos los rostros se marcan como 'desconocido'.")
