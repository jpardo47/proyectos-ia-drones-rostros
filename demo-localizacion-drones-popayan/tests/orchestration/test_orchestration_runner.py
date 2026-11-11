import builtins
import sys

import pytest

from src.orchestration.runner import run_demo
from src.storage import Storage
from tests.s2_support import FakeIngestion, FakePipeline, FakeValidator, fake_simulate


def _run(db, **kw):
    validator = FakeValidator()
    pipeline = FakePipeline(lost_after_s=30.0)
    summary = run_demo(
        "basico", 42, db_path=db, simulate=fake_simulate, ingestion_agent=FakeIngestion(),
        validator_agent=validator, pipeline=pipeline, **kw,
    )
    return summary, validator, pipeline


def test_run_demo_summary_and_storage(tmp_path):
    db = tmp_path / "demo.sqlite"
    summary, validator, pipeline = _run(db)
    assert summary["is_simulated"] is True and "SIMULADOS" in summary["titulo"]
    assert summary["scenario"] == "basico" and summary["seed"] == 42
    assert summary["events"] == 8
    assert summary["rejected"] == 1 and summary["rejected_by_code"] == {"MALFORMED": 1}
    assert summary["duplicates"] == 1
    assert summary["accepted"] == 6
    assert summary["tracks"] == 1 and summary["alerts"] == 1
    # tras la ultima observacion el motor pudo declarar la perdida (lotes vacios adicionales)
    assert summary["tracks_by_state"] == {"SEGUIMIENTO_PERDIDO": 1}
    st = Storage(db)
    c = st.counts()
    assert c["observations"] == 6 and c["rejected_inputs"] == 1 and c["tracks"] == 1
    assert c["stations"] == 7 and c["scenario_truth"] == 3 and c["runs"] == 1
    assert st.get_track("TRK-1").is_lost is True
    assert len(st.list_related_locations()) == 6
    st.close()


def test_batches_use_end_of_batch_time_and_station_status(tmp_path):
    summary, validator, pipeline = _run(tmp_path / "d.sqlite", batch_seconds=5.0)
    # el primer lote (0-5 s) termina en t0+5 s y contiene los eventos recibidos antes
    first_obs, first_now, status = pipeline.calls[0]
    assert (first_now - pipeline.calls[0][1]).total_seconds() == 0
    assert first_now.second == 5 and len(first_obs) == 4  # E0, E1 (x2 llegan), E2 sin el malformado
    assert status["INST-SIM-01"].value == "online" and len(status) == 7
    # los instantes now_utc crecen de 5 en 5 s y hay lotes vacios al final
    times = [c[1] for c in pipeline.calls]
    assert all((b - a).total_seconds() == 5.0 for a, b in zip(times, times[1:]))
    assert any(len(c[0]) == 0 for c in pipeline.calls[-3:])
    assert all(v in times for v in validator.now_values)


def test_reset_flag(tmp_path):
    db = tmp_path / "d.sqlite"
    _run(db)
    _run(db, reset=True)
    st = Storage(db)
    assert st.counts()["runs"] == 1
    st.close()
    summary, *_ = _run(db, reset=False)
    st = Storage(db)
    assert st.counts()["runs"] == 2 and st.counts()["observations"] == 6
    st.close()


def test_deterministic_summary(tmp_path):
    a, *_ = _run(tmp_path / "a.sqlite")
    b, *_ = _run(tmp_path / "b.sqlite")
    for k in ("events", "accepted", "rejected_by_code", "duplicates", "tracks_by_state", "alerts", "batches"):
        assert a[k] == b[k]


def test_injected_storage_memory():
    st = Storage(":memory:")
    summary = run_demo("basico", 1, storage=st, simulate=fake_simulate, ingestion_agent=FakeIngestion(),
                       validator_agent=FakeValidator(), pipeline=FakePipeline())
    assert summary["db_path"] == ":memory:" and st.counts()["tracks"] == 1
    st.list_stations()  # la conexion sigue abierta (no la cierra run_demo)


def test_invalid_batch_seconds():
    with pytest.raises(ValueError):
        run_demo(batch_seconds=0, simulate=fake_simulate)


def test_missing_modules_give_clear_spanish_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("src.ingestion"):
            raise ImportError("simulado: no existe")
        return real_import(name, *a, **k)

    for m in [m for m in sys.modules if m.startswith("src.ingestion")]:
        monkeypatch.delitem(sys.modules, m)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError) as exc:
        run_demo(db_path=":memory:", simulate=fake_simulate, pipeline=FakePipeline())
    assert "No se pudo importar el modulo" in str(exc.value)
