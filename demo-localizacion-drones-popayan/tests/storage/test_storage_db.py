import sqlite3

import pytest

from src.contracts import DetectionState, LocationRole, ReviewStatus, SensorType, load_default_stations
from src.stations import StationRegistry
from src.storage import Storage
from tests.s2_support import (at, make_ingestion, make_pipeline_result, make_rejected, make_track,
                              make_truth)


@pytest.fixture()
def st():
    s = Storage(":memory:")
    yield s
    s.close()


def test_stations_roundtrip_and_inst_sim_without_coordinates(st):
    st.upsert_stations(load_default_stations())
    got = st.list_stations()
    assert len(got) == 7
    inst = [s for s in got if s.station_id.startswith("INST-SIM")]
    assert len(inst) == 2 and all(s.latitude is None and s.longitude is None for s in inst)
    st.upsert_stations(load_default_stations())  # idempotente
    assert len(st.list_stations()) == 7


def test_observation_roundtrip_16_fields_and_related_locations(st):
    ing = make_ingestion("E1")
    st.save_ingestion(ing)
    st.save_ingestion(ing)  # sin duplicar
    got = st.list_observations()
    assert len(got) == 1 and got[0] == ing.observation
    rel = st.list_related_locations("E1")
    assert {r["location"].role for r in rel} == {LocationRole.DRONE, LocationRole.CONTROL_STATION,
                                                 LocationRole.TAKEOFF_POINT}


def test_acoustic_observation_without_coordinates_roundtrip(st):
    st.save_ingestion(make_ingestion("A1", with_related=False, sensor=SensorType.ACOUSTIC, station="CIV-03"))
    o = st.list_observations(sensor_type="acoustic")[0]
    assert o.latitude is None and o.longitude is None and o.altitude is None


def test_observation_filters(st):
    st.save_ingestion(make_ingestion("E1", station="CIV-01", t=0))
    st.save_ingestion(make_ingestion("E2", station="CIV-02", t=10))
    st.save_ingestion(make_ingestion("A1", station="CIV-02", t=20, sensor=SensorType.ACOUSTIC, with_related=False))
    assert [o.event_id for o in st.list_observations(station_id="CIV-02")] == ["E2", "A1"]
    assert [o.event_id for o in st.list_observations(sensor_type="acoustic")] == ["A1"]
    assert [o.event_id for o in st.list_observations(desde=at(5), hasta=at(15))] == ["E2"]
    assert len(st.list_observations(limit=2)) == 2


def test_sql_is_parameterized(st):
    st.save_ingestion(make_ingestion("E1"))
    assert st.list_observations(station_id="CIV-01' OR '1'='1") == []
    assert st.counts()["observations"] == 1


def test_rejected_roundtrip(st):
    st.save_rejected(make_rejected("OUT_OF_RANGE"))
    got = st.list_rejected()
    assert len(got) == 1 and got[0].reason_code == "OUT_OF_RANGE" and got[0].station_id == "CIV-02"


def test_pipeline_result_roundtrip_and_no_duplicates(st):
    res = make_pipeline_result()
    st.save_pipeline_result(res)
    st.save_pipeline_result(res)
    c = st.counts()
    assert (c["tracks"], c["decisions"], c["alerts"], c["audit_events"]) == (1, 1, 1, 1)
    assert c["track_points"] == 3
    assert st.get_track("TRK-1") == res.tracks[0]
    assert st.get_track("NOPE") is None
    assert st.list_decisions("TRK-1") == res.decisions
    assert st.list_alerts() == res.alerts
    assert st.list_audit() == res.audit_events
    assert st.latest_decisions()["TRK-1"].state == DetectionState.DETECCION_POSIBLE


def test_track_upsert_replaces_points(st):
    st.save_pipeline_result(make_pipeline_result())
    longer = make_pipeline_result().model_copy(update={"tracks": [make_track(n_points=5)]})
    st.save_pipeline_result(longer)
    assert len(st.get_track("TRK-1").points) == 5
    shorter = make_pipeline_result().model_copy(update={"tracks": [make_track(n_points=1, lost=True)]})
    st.save_pipeline_result(shorter)
    t = st.get_track("TRK-1")
    assert len(t.points) == 1 and t.is_lost
    assert st.counts()["track_points"] == 1


def test_track_without_points(st):
    res = make_pipeline_result().model_copy(update={"tracks": [make_track(n_points=0)]})
    st.save_pipeline_result(res)
    assert st.get_track("TRK-1").points == []


def test_existing_alert_review_not_overwritten_by_pipeline(st):
    st.save_pipeline_result(make_pipeline_result())
    st.review_alert("ALR-1", ReviewStatus.CONFIRMADA, "ana", "ok")
    st.save_pipeline_result(make_pipeline_result())
    assert st.get_alert("ALR-1").review_status == ReviewStatus.CONFIRMADA


def test_review_alert_and_audit(st):
    st.save_pipeline_result(make_pipeline_result())
    when = at(100)
    out = st.review_alert("ALR-1", ReviewStatus.DESCARTADA, "ana", "falsa alarma simulada", when_utc=when)
    assert out.review_status == ReviewStatus.DESCARTADA and out.reviewed_by == "ana"
    assert out.reviewed_at_utc == when and out.review_note == "falsa alarma simulada"
    assert st.list_alerts("descartada")[0].alert_id == "ALR-1"
    assert st.list_alerts("pendiente") == []
    events = [e for e in st.list_audit() if e.actor == "operador:ana"]
    assert len(events) == 1 and events[0].subject == "ALR-1" and events[0].details["status"] == "descartada"
    with pytest.raises(KeyError):
        st.review_alert("NOPE", ReviewStatus.CONFIRMADA, "ana", None)
    with pytest.raises(ValueError):
        st.review_alert("ALR-1", ReviewStatus.CONFIRMADA, "  ", None)


def test_truth_is_separate_and_marked_simulated(st):
    st.save_truth("basico", make_truth())
    st.save_truth("basico", make_truth())  # reemplaza
    rows = st.list_truth("basico")
    assert len(rows) == 3 and all(r["is_simulated"] and "SIMULADO" in r["label"] for r in rows)
    assert st.counts()["observations"] == 0 and st.counts()["scenario_truth"] == 3


def test_reset_and_counts(st):
    st.save_ingestion(make_ingestion("E1"))
    st.save_pipeline_result(make_pipeline_result())
    st.save_rejected(make_rejected())
    st.save_run("basico", 42, {"a": 1})
    assert st.counts()["runs"] == 1
    st.reset()
    assert sum(st.counts().values()) == 0
    st.save_ingestion(make_ingestion("E1"))  # sigue usable
    assert st.counts()["observations"] == 1


def test_file_db_created_and_persisted(tmp_path):
    p = tmp_path / "sub" / "demo.sqlite"
    s = Storage(p)
    s.save_ingestion(make_ingestion("E1"))
    s.close()
    assert p.exists()
    s2 = Storage(p)
    assert len(s2.list_observations()) == 1
    s2.close()


def test_truth_table_rejects_non_simulated_flag(st):
    with pytest.raises(sqlite3.IntegrityError):
        st._exec("INSERT INTO scenario_truth(scenario_id, drone_id, timestamp_utc, latitude, longitude, "
                 "altitude_agl_m, emits_remote_id, emits_sound, is_simulated) VALUES ('x','d','t',0,0,0,1,1,0)")


def test_station_registry_status_and_sync(st):
    reg = StationRegistry(storage=st)
    assert len(st.list_stations()) == 7
    out = reg.set_status("CIV-01", "offline", at(10))
    assert out.status.value == "offline" and out.status_timestamp_utc == at(10)
    assert reg.status_map()["CIV-01"].value == "offline"
    assert next(s for s in st.list_stations() if s.station_id == "CIV-01").status.value == "offline"
    assert reg.get("NOPE") is None
    with pytest.raises(KeyError):
        reg.set_status("NOPE", "online", at(1))
    with pytest.raises(ValueError):
        reg.set_status("CIV-01", "online", at(1).replace(tzinfo=None))
    assert [s.station_id for s in reg.without_location()] == ["INST-SIM-01", "INST-SIM-02"]
