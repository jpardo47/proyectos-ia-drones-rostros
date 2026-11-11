"""Dashboard Streamlit de la demo de localizacion multisensor (P3).

Ejecutar:  streamlit run src/dashboard/app.py   (o ``python app.py dashboard``)
Todos los datos mostrados son SIMULADOS; los nodos son FICTICIOS.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.api.exports import observations_csv, stations_geojson, tracks_geojson  # noqa: E402
from src.contracts import POPAYAN_REFERENCE, LocationRole, ReviewStatus  # noqa: E402
from src.storage.db import DEFAULT_DB_PATH, Storage  # noqa: E402

BANNER = "DATOS SIMULADOS — demostración de investigación, no son detecciones reales"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
FALLBACK_SCENARIOS = [
    "basico", "sin_remote_id", "duplicados", "contradictorio", "corroborado", "perdida_senal",
    "estacion_caida", "malformados", "sin_estacion_control", "rangos_100m_10km",
]

LEGEND = [
    ("#1f77b4", "Estaciones civiles ficticias"),
    ("#ff7f0e", "Trayectorias observadas (posiciones reportadas)"),
    ("#d62728", "Posición reportada del dron"),
    ("#2ca02c", "Estación de control reportada"),
    ("#9467bd", "Punto de despegue reportado"),
    ("#7f7f7f", "Verdad del simulador (opcional, apagada por defecto)"),
]


def db_path() -> str:
    return os.environ.get("POPAYAN_DB_PATH") or str(DEFAULT_DB_PATH)


@st.cache_resource
def _storage(path: str) -> Storage:
    return Storage(path)


def scenario_names() -> list[str]:
    try:
        from src.simulation.scenario import list_scenarios

        names = list(list_scenarios())
        return names or FALLBACK_SCENARIOS
    except Exception:  # el simulador lo escribe otro equipo; la lista fija sirve de respaldo
        return FALLBACK_SCENARIOS


def render_banner() -> None:
    st.markdown(
        f"<div style='background:#b71c1c;color:#fff;padding:10px 14px;border-radius:6px;"
        f"font-weight:700;text-align:center;font-size:1.05rem'>{BANNER}</div>",
        unsafe_allow_html=True,
    )


def render_sidebar(store: Storage) -> dict:
    st.sidebar.header("Simulación")
    scenario = st.sidebar.selectbox("Escenario", scenario_names(), index=0)
    seed = int(st.sidebar.number_input("Semilla", min_value=0, max_value=2**31 - 1, value=42, step=1))
    if st.sidebar.button("Ejecutar demo", type="primary"):
        try:
            from src.orchestration.runner import run_demo

            with st.spinner("Ejecutando escenario simulado..."):
                summary = run_demo(scenario, seed, storage=store, reset=True)
            st.session_state["last_summary"] = summary
            st.sidebar.success("Demo ejecutada (datos simulados).")
        except ImportError as exc:
            st.sidebar.error(f"Faltan módulos de la demo: {exc}")
        except Exception as exc:  # noqa: BLE001 - se muestra al usuario en lugar de romper la página
            st.sidebar.error(f"No se pudo ejecutar la demo: {exc}")
    st.sidebar.divider()
    st.sidebar.header("Mapa")
    mode = st.sidebar.radio("Vista", ["Mapa con teselas OpenStreetMap", "Vista provisional (sin teselas)"])
    show_truth = st.sidebar.checkbox("Mostrar verdad del simulador", value=False,
                                     help="Estado verdadero del escenario simulado; no es una observación.")
    st.sidebar.caption(f"Base de datos: {store.db_path}")
    return {"mode": mode, "show_truth": show_truth}


def _dedupe_points(items: list[dict], decimals: int = 5) -> list[dict]:
    seen, out = set(), []
    for it in items:
        loc = it["location"]
        key = (loc.role.value, round(loc.latitude, decimals), round(loc.longitude, decimals))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def collect_layers(store: Storage) -> dict:
    stations = store.list_stations()
    related = store.list_related_locations()
    obs = [o for o in store.list_observations() if o.has_position]
    return {
        "stations": [s for s in stations if s.has_location],
        "abstract": [s for s in stations if not s.has_location],
        "tracks": store.list_tracks(),
        "latest": store.latest_decisions(),
        "drone": [r for r in related if r["location"].role == LocationRole.DRONE],
        "control": _dedupe_points([r for r in related if r["location"].role == LocationRole.CONTROL_STATION]),
        "takeoff": _dedupe_points([r for r in related if r["location"].role == LocationRole.TAKEOFF_POINT]),
        "obs_positions": obs,
        "truth": store.list_truth(),
    }


def build_folium_map(layers: dict, show_truth: bool):
    import folium

    m = folium.Map(location=[POPAYAN_REFERENCE["latitude"], POPAYAN_REFERENCE["longitude"]],
                   zoom_start=13, tiles=None)
    folium.TileLayer(tiles=OSM_TILES, attr=OSM_ATTRIBUTION, name="OpenStreetMap", control=False).add_to(m)

    g_st = folium.FeatureGroup(name="Estaciones civiles ficticias")
    for s in layers["stations"]:
        folium.Marker([s.latitude, s.longitude], icon=folium.Icon(color="blue", icon="wifi", prefix="fa"),
                      tooltip=f"{s.station_id} (FICTICIA, simulada) · {s.status.value}",
                      popup=f"{s.name}<br>Sensores virtuales: {', '.join(v.value for v in s.virtual_sensors)}").add_to(g_st)
    g_st.add_to(m)

    g_tr = folium.FeatureGroup(name="Trayectorias observadas")
    for t in layers["tracks"]:
        pts = [(p.latitude, p.longitude) for p in t.points]
        d = layers["latest"].get(t.track_id)
        tip = f"{t.track_id} · {d.state.value if d else 'sin estado'} (SIMULADO)"
        if len(pts) >= 2:
            folium.PolyLine(pts, color="#ff7f0e", weight=3, opacity=0.9, tooltip=tip).add_to(g_tr)
        elif pts:
            folium.CircleMarker(pts[0], radius=5, color="#ff7f0e", fill=True, tooltip=tip).add_to(g_tr)
    g_tr.add_to(m)

    g_dr = folium.FeatureGroup(name="Posición reportada del dron")
    for t in layers["tracks"]:
        if t.points:
            p = t.points[-1]
            folium.Marker([p.latitude, p.longitude], icon=folium.Icon(color="red", icon="plane", prefix="fa"),
                          tooltip=f"Última posición reportada · {t.track_id} (SIMULADA)").add_to(g_dr)
    for r in layers["drone"][-500:]:
        loc = r["location"]
        folium.CircleMarker([loc.latitude, loc.longitude], radius=2, color="#d62728", fill=True,
                            tooltip="Posición reportada del dron (SIMULADA)").add_to(g_dr)
    g_dr.add_to(m)

    g_ct = folium.FeatureGroup(name="Estación de control reportada")
    for r in layers["control"]:
        loc = r["location"]
        folium.Marker([loc.latitude, loc.longitude], icon=folium.Icon(color="green", icon="gamepad", prefix="fa"),
                      tooltip=f"Estación de control reportada (no verificada, SIMULADA) · {loc.detail or ''}").add_to(g_ct)
    g_ct.add_to(m)

    g_tk = folium.FeatureGroup(name="Punto de despegue reportado")
    for r in layers["takeoff"]:
        loc = r["location"]
        folium.Marker([loc.latitude, loc.longitude], icon=folium.Icon(color="purple", icon="flag", prefix="fa"),
                      tooltip="Punto de despegue reportado (no verificado, SIMULADO)").add_to(g_tk)
    g_tk.add_to(m)

    g_tv = folium.FeatureGroup(name="Verdad del simulador (SIMULADO)", show=show_truth)
    by_drone: dict[str, list] = {}
    for row in layers["truth"]:
        by_drone.setdefault(row["drone_id"], []).append((row["latitude"], row["longitude"]))
    for drone_id, pts in by_drone.items():
        folium.PolyLine(pts, color="#7f7f7f", weight=2, dash_array="6", tooltip=f"Verdad del simulador · {drone_id}").add_to(g_tv)
    g_tv.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def provisional_frame(layers: dict, show_truth: bool) -> pd.DataFrame:
    rows = []

    def add(lat, lon, color, label):
        rows.append({"lat": lat, "lon": lon, "color": color, "etiqueta": label})

    for s in layers["stations"]:
        add(s.latitude, s.longitude, "#1f77b4", f"estación ficticia {s.station_id}")
    for t in layers["tracks"]:
        for p in t.points:
            add(p.latitude, p.longitude, "#ff7f0e", f"trayectoria {t.track_id}")
    for r in layers["control"]:
        add(r["location"].latitude, r["location"].longitude, "#2ca02c", "control reportada")
    for r in layers["takeoff"]:
        add(r["location"].latitude, r["location"].longitude, "#9467bd", "despegue reportado")
    if show_truth:
        for r in layers["truth"]:
            add(r["latitude"], r["longitude"], "#7f7f7f", "verdad del simulador")
    return pd.DataFrame(rows, columns=["lat", "lon", "color", "etiqueta"])


def render_map(layers: dict, opts: dict) -> None:
    st.subheader("Mapa (cartografía pública + objetos virtuales)")
    st.markdown(" &nbsp; ".join(f"<span style='color:{c}'>■</span> {label}" for c, label in LEGEND),
                unsafe_allow_html=True)
    if opts["mode"].startswith("Mapa"):
        try:
            from streamlit_folium import st_folium

            st_folium(build_folium_map(layers, opts["show_truth"]), height=520, use_container_width=True,
                      returned_objects=[])
            st.caption(f"Teselas: {OSM_ATTRIBUTION}. Si no cargan (sin red), use la vista provisional.")
            return
        except Exception as exc:  # noqa: BLE001
            st.warning(f"No se pudo dibujar el mapa con teselas ({exc}). Se muestra la vista provisional.")
    df = provisional_frame(layers, opts["show_truth"])
    if df.empty:
        st.info("Sin puntos para mostrar. Ejecute una demo desde la barra lateral.")
    else:
        st.map(df, latitude="lat", longitude="lon", color="color", size=20)
        st.caption("Vista provisional sin teselas: solo puntos con coordenadas.")


def render_abstract_nodes(layers: dict) -> None:
    st.subheader("Nodos institucionales abstractos (sin ubicación geográfica)")
    st.caption("Fuentes de datos lógicas y ficticias. No representan posiciones, equipos ni instalaciones reales.")
    rows = [{
        "nodo": s.station_id, "nombre": s.name, "estado": s.status.value,
        "sensores virtuales": ", ".join(v.value for v in s.virtual_sensors),
        "calidad de datos": s.data_quality, "ubicación": "no aplica",
    } for s in layers["abstract"]]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("Sin nodos abstractos cargados.")


def _df(models, **kw) -> pd.DataFrame:
    return pd.DataFrame([m.model_dump(mode="json", **kw) for m in models])


def render_tables(store: Storage, layers: dict) -> None:
    t_obs, t_trk, t_alr, t_rej, t_aud, t_exp = st.tabs(
        ["Observaciones", "Estados por track", "Alertas y revisión", "Rechazados", "Auditoría", "Exportar"])
    observations = store.list_observations()

    with t_obs:
        df = _df(observations)
        if df.empty:
            st.info("Sin observaciones.")
        else:
            c1, c2 = st.columns(2)
            sts = c1.multiselect("Estación", sorted(df["station_id"].unique()))
            sens = c2.multiselect("Sensor", sorted(df["sensor_type"].unique()))
            if sts:
                df = df[df["station_id"].isin(sts)]
            if sens:
                df = df[df["sensor_type"].isin(sens)]
            st.dataframe(df, hide_index=True, width="stretch")

    with t_trk:
        rows = []
        for t in layers["tracks"]:
            d = layers["latest"].get(t.track_id)
            rows.append({
                "track": t.track_id, "objeto": t.object_id, "estado": d.state.value if d else "—",
                "motivo (reason)": d.reason if d else "", "regla (rule_id)": d.rule_id if d else "",
                "requiere revisión humana": d.requires_human_review if d else None,
                "estaciones": ", ".join(t.station_ids), "sensores": ", ".join(s.value for s in t.sensor_types),
                "puntos": len(t.points), "perdido": t.is_lost, "simulado": t.is_simulated,
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            with st.expander("Historial de decisiones"):
                st.dataframe(_df(store.list_decisions()), hide_index=True, width="stretch")
        else:
            st.info("Sin tracks.")

    with t_alr:
        st.caption("Las alertas son informativas y requieren revisión humana. No sugieren acciones.")
        alerts = store.list_alerts()
        if not alerts:
            st.info("Sin alertas.")
        else:
            st.dataframe(_df(alerts), hide_index=True, width="stretch")
            with st.form("review_form", clear_on_submit=True):
                alert_id = st.selectbox("Alerta", [a.alert_id for a in alerts])
                decision = st.radio("Revisión", ["confirmar", "descartar"], horizontal=True)
                reviewer = st.text_input("Revisor (usuario)", max_chars=64)
                note = st.text_area("Nota", max_chars=1000)
                if st.form_submit_button("Registrar revisión"):
                    if not reviewer.strip():
                        st.error("Indique quién revisa la alerta.")
                    else:
                        status = ReviewStatus.CONFIRMADA if decision == "confirmar" else ReviewStatus.DESCARTADA
                        store.review_alert(alert_id, status, reviewer.strip(), note or None)
                        st.success(f"Alerta {alert_id}: {status.value}. Queda registrada en la auditoría.")
                        st.rerun()

    with t_rej:
        rej = store.list_rejected()
        st.dataframe(_df(rej), hide_index=True, width="stretch") if rej else st.info("Sin rechazados.")

    with t_aud:
        aud = store.list_audit()
        if aud:
            df = _df(aud)
            df["details"] = df["details"].apply(lambda d: json.dumps(d, ensure_ascii=False))
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.info("Sin eventos de auditoría.")

    with t_exp:
        st.caption("Las exportaciones llevan la marca DATOS SIMULADOS.")
        st.download_button("Descargar observaciones (CSV)", observations_csv(observations),
                           file_name="observaciones_SIMULADAS.csv", mime="text/csv")
        st.download_button("Descargar trayectorias (GeoJSON)",
                           json.dumps(tracks_geojson(layers["tracks"], layers["latest"])),
                           file_name="trayectorias_SIMULADAS.geojson", mime="application/geo+json")
        st.download_button("Descargar estaciones ficticias (GeoJSON)",
                           json.dumps(stations_geojson(store.list_stations())),
                           file_name="estaciones_FICTICIAS.geojson", mime="application/geo+json")


def render_summary(store: Storage) -> None:
    c = store.counts()
    cols = st.columns(5)
    cols[0].metric("Observaciones", c["observations"])
    cols[1].metric("Tracks", c["tracks"])
    cols[2].metric("Decisiones", c["decisions"])
    cols[3].metric("Alertas", c["alerts"])
    cols[4].metric("Rechazados", c["rejected_inputs"])
    summary = st.session_state.get("last_summary")
    if summary:
        with st.expander("Resumen de la última ejecución (SIMULADA)"):
            st.json(summary)


def main() -> None:
    st.set_page_config(page_title="Demo multisensor Popayán (SIMULADA)", layout="wide")
    render_banner()
    st.title("Demo de localización multisensor — Popayán")
    st.caption("Proyecto de investigación y simulación. Nodos ficticios; datos simulados; "
               "las pruebas de distancia validan el software, no el alcance de ningún equipo.")
    store = _storage(db_path())
    opts = render_sidebar(store)
    render_summary(store)
    layers = collect_layers(store)
    render_map(layers, opts)
    render_abstract_nodes(layers)
    render_tables(store, layers)
    st.caption(f"Cartografía: {OSM_ATTRIBUTION}")


main()
