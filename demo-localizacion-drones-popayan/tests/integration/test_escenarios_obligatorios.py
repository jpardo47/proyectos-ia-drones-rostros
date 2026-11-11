"""Pruebas de integracion: los 12 escenarios obligatorios del plan maestro (P3).

Usan los modulos reales (simulador, ingesta, validador, motor, almacenamiento) mediante
``run_demo`` con una base SQLite temporal. No hay mocks. Todos los datos son SIMULADOS.
Cada escenario se ejecuta una sola vez (fixture de ambito de modulo).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.contracts import DetectionState, Observation
from src.contracts.observation import DataOrigin, SensorType
from src.orchestration.runner import run_demo
from src.storage.db import Storage

pytestmark = pytest.mark.integration

SEED = 42


# --------------------------------------------------------------------- utilidades
def _ejecutar(directorio: Path, escenario: str, seed: int = SEED):
    """Ejecuta un escenario sobre una base temporal. Devuelve (resumen, ruta_db, error)."""
    db = directorio / f"{escenario}-{seed}.sqlite"
    try:
        resumen = run_demo(escenario, seed, db_path=db)
        return resumen, db, None
    except Exception as exc:  # se conserva para que la prueba lo reporte
        return None, db, exc


def _q(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, params).fetchall()


def _q_dict(db: Path, sql: str, params: tuple = ()) -> list[dict]:
    with closing(sqlite3.connect(db)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def _json_decisiones(db: Path) -> list[dict]:
    return [json.loads(r[0]) for r in _q(db, "SELECT json FROM decisions ORDER BY decision_id")]


def _json_alertas(db: Path) -> list[dict]:
    return [json.loads(r[0]) for r in _q(db, "SELECT json FROM alerts ORDER BY alert_id")]


@pytest.fixture(scope="module")
def directorio(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("escenarios_integracion")


@pytest.fixture(scope="module")
def ejec_basico(directorio):
    return _ejecutar(directorio, "basico")


@pytest.fixture(scope="module")
def ejec_perdida(directorio):
    return _ejecutar(directorio, "perdida_senal")


@pytest.fixture(scope="module")
def ejec_duplicados(directorio):
    return _ejecutar(directorio, "duplicados")


@pytest.fixture(scope="module")
def ejec_contradictorio(directorio):
    return _ejecutar(directorio, "contradictorio")


@pytest.fixture(scope="module")
def ejec_corroborado(directorio):
    return _ejecutar(directorio, "corroborado")


@pytest.fixture(scope="module")
def ejec_malformados(directorio):
    return _ejecutar(directorio, "malformados")


@pytest.fixture(scope="module")
def ejec_sin_estacion(directorio):
    return _ejecutar(directorio, "sin_estacion_control")


@pytest.fixture(scope="module")
def ejec_estacion_caida(directorio):
    return _ejecutar(directorio, "estacion_caida")


def _resumen_ok(ejec):
    resumen, db, error = ejec
    assert error is None, f"run_demo lanzo excepcion: {error!r}"
    assert resumen is not None
    return resumen, db


# ----------------------------------------------------------------- escenarios
def test_01_observacion_valida_produce_deteccion_posible(ejec_basico):
    resumen, db = _resumen_ok(ejec_basico)
    estados = {r[0] for r in _q(db, "SELECT state FROM decisions")}
    assert DetectionState.DETECCION_POSIBLE.value in estados
    assert resumen["rejected"] == 0


def test_02_perdida_de_senal_marca_seguimiento_perdido_con_motivo(ejec_perdida):
    _, db = _resumen_ok(ejec_perdida)
    filas = _q_dict(
        db,
        "SELECT reason, rule_id FROM decisions WHERE state = ?",
        (DetectionState.SEGUIMIENTO_PERDIDO.value,),
    )
    assert filas, "ningun track alcanzo SEGUIMIENTO_PERDIDO"
    assert any(f["reason"] and f["reason"].strip() and f["rule_id"] and f["rule_id"].strip()
               for f in filas)


def test_03_duplicados_se_descartan_y_no_repiten_event_id(ejec_duplicados):
    resumen, db = _resumen_ok(ejec_duplicados)
    assert resumen["duplicates"] > 0
    repetidos = _q(db, "SELECT event_id, COUNT(*) FROM observations GROUP BY event_id HAVING COUNT(*) > 1")
    assert repetidos == []


def test_04_fuentes_contradictorias_requieren_revision(ejec_contradictorio):
    _, db = _resumen_ok(ejec_contradictorio)
    decisiones = _json_decisiones(db)
    revision = [d for d in decisiones if d.get("state") == DetectionState.REQUIERE_REVISION.value]
    assert revision, "no hay decisiones REQUIERE_REVISION"
    assert any(d.get("requires_human_review") is True for d in revision)
    estados = {r[0] for r in _q(db, "SELECT state FROM decisions")}
    assert DetectionState.REQUIERE_REVISION.value in estados


def test_05_dos_fuentes_independientes_corroboran(ejec_corroborado):
    _, db = _resumen_ok(ejec_corroborado)
    estados = {r[0] for r in _q(db, "SELECT state FROM decisions")}
    assert DetectionState.DETECCION_CORROBORADA.value in estados


def test_06_datos_obsoletos_rechazados_stale_y_tracks_perdidos(ejec_malformados):
    _, db = _resumen_ok(ejec_malformados)
    codigos = {r[0] for r in _q(db, "SELECT reason_code FROM rejected_inputs")}
    assert "STALE" in codigos, f"codigos rechazados: {sorted(codigos)}"

    with closing(Storage(db)) as almacen:
        tracks = almacen.list_tracks()
        ultima = almacen.latest_decisions()
    assert tracks, "no hay tracks tras el escenario"
    estados_finales = {t.track_id: (ultima[t.track_id].state.value if t.track_id in ultima else None)
                       for t in tracks}
    no_perdidos = {k: v for k, v in estados_finales.items() if v != DetectionState.SEGUIMIENTO_PERDIDO.value}
    assert not no_perdidos, f"tracks que no quedaron en SEGUIMIENTO_PERDIDO: {no_perdidos}"


def test_07_dron_sin_estacion_de_control_se_acepta_con_control_desconocido(ejec_sin_estacion):
    _, db = _resumen_ok(ejec_sin_estacion)
    roles = [r[0] for r in _q(db, "SELECT role FROM related_locations")]
    assert "control_station" not in roles
    aceptadas_rid = _q(db, "SELECT COUNT(*) FROM observations WHERE sensor_type = 'remote_id'")[0][0]
    assert aceptadas_rid > 0


def test_08_punto_de_despegue_sin_controlador(ejec_sin_estacion):
    _, db = _resumen_ok(ejec_sin_estacion)
    roles = [r[0] for r in _q(db, "SELECT role FROM related_locations")]
    assert "takeoff_point" in roles
    assert "control_station" not in roles


def test_09_audio_sin_coordenadas_y_sin_puntos(ejec_basico):
    _, db = _resumen_ok(ejec_basico)
    acusticas = _q(
        db,
        "SELECT COUNT(*) FROM observations WHERE sensor_type = 'acoustic' "
        "AND (latitude IS NOT NULL OR longitude IS NOT NULL OR altitude IS NOT NULL)",
    )[0][0]
    assert acusticas == 0
    assert _q(db, "SELECT COUNT(*) FROM observations WHERE sensor_type = 'acoustic'")[0][0] > 0
    solo_acusticos = [
        r[0] for r in _q(db, "SELECT track_id, sensor_types FROM tracks")
        if json.loads(r[1]) == ["acoustic"]
    ]
    assert solo_acusticos, "se esperaban tracks de presencia solo acusticos en 'basico'"
    for track_id in solo_acusticos:
        puntos = _q(db, "SELECT COUNT(*) FROM track_points WHERE track_id = ?", (track_id,))[0][0]
        assert puntos == 0, f"track solo acustico {track_id} tiene {puntos} puntos"


def test_10_estacion_caida_queda_offline_y_rechaza(ejec_estacion_caida):
    _, db = _resumen_ok(ejec_estacion_caida)
    estado = _q(db, "SELECT status FROM stations WHERE station_id = 'CIV-02'")
    assert estado and estado[0][0] == "offline"
    rechazos = _q(db, "SELECT COUNT(*) FROM rejected_inputs WHERE reason_code = 'STATION_OFFLINE'")[0][0]
    assert rechazos > 0


def test_11_datos_malformados_no_lanzan_y_se_rechazan_con_motivo(ejec_malformados):
    _, db = _resumen_ok(ejec_malformados)
    filas = _q_dict(db, "SELECT reason_code, reason FROM rejected_inputs")
    assert filas, "rejected_inputs vacio"
    for f in filas:
        assert f["reason_code"] and f["reason_code"].strip()
        assert f["reason"] and f["reason"].strip()


def test_12_simulado_no_se_mezcla_y_contrato_rechaza_sensor_simulado(ejec_basico):
    _, db = _resumen_ok(ejec_basico)
    obs = _q(db, "SELECT is_simulated, data_origin FROM observations")
    assert obs and all(i == 1 and o == "simulation" for i, o in obs)
    assert all(r[0] == 1 for r in _q(db, "SELECT is_simulated FROM tracks"))
    assert all(d.get("is_simulated") is True for d in _json_decisiones(db))
    assert all(a.get("is_simulated") is True for a in _json_alertas(db))

    with pytest.raises(ValueError):
        Observation(
            event_id="obs-invalida-1",
            station_id="CIV-01",
            sensor_type=SensorType.RF,
            timestamp_utc=datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc),
            data_origin=DataOrigin.SENSOR,
            is_simulated=True,
        )


# ------------------------------------------------------------------- extras
def test_extra_nodos_institucionales_sin_coordenadas(ejec_basico):
    _, db = _resumen_ok(ejec_basico)
    filas = _q(db, "SELECT station_id, latitude, longitude FROM stations "
                   "WHERE station_id IN ('INST-SIM-01', 'INST-SIM-02')")
    assert {f[0] for f in filas} == {"INST-SIM-01", "INST-SIM-02"}
    assert all(f[1] is None and f[2] is None for f in filas)


def test_extra_todas_las_alertas_son_informativas(ejec_basico):
    _, db = _resumen_ok(ejec_basico)
    alertas = _json_alertas(db)
    assert alertas, "no hay alertas en basico"
    assert all(a.get("severity") == "informativa" for a in alertas)


def test_extra_determinismo_misma_semilla_mismas_decisiones(ejec_basico, directorio):
    resumen_a, db_a = _resumen_ok(ejec_basico)
    resumen_b, db_b, error = _ejecutar(directorio, "basico", seed=SEED)
    assert error is None, f"segunda ejecucion lanzo: {error!r}"
    ids_a = {r[0] for r in _q(db_a, "SELECT decision_id FROM decisions")}
    ids_b = {r[0] for r in _q(db_b, "SELECT decision_id FROM decisions")}
    assert ids_a == ids_b and ids_a
    for clave in ("accepted", "rejected", "duplicates", "tracks", "decisions", "alerts",
                  "observaciones_validas"):
        assert resumen_a[clave] == resumen_b[clave], clave
