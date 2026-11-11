import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.contracts import IngestionResult, RawEvent, RejectedInput, load_default_stations
from src.ingestion import IngestionAgent, ReceiverAdapter, ReceptionAuthorization, ReplayFileAdapter, ValidatorAgent
from src.ingestion import adapters as adapters_module

EXAMPLES = Path(__file__).resolve().parents[2] / "data" / "examples" / "remote_id"
NOW = datetime(2026, 1, 15, 15, 0, 1, tzinfo=timezone.utc)
KNOWN = {s.station_id for s in load_default_stations()}


def run_file(name):
    adapter = ReplayFileAdapter(EXAMPLES / name)
    ingest, validate = IngestionAgent(), ValidatorAgent(KNOWN)
    accepted, rejected = [], []
    for event in adapter.events():
        assert isinstance(event, RawEvent)
        res = ingest.ingest(event)
        if isinstance(res, IngestionResult):
            res = validate.validate(res, NOW)
        (accepted if isinstance(res, IngestionResult) else rejected).append(res)
    return adapter, accepted, rejected


def test_valid_examples_all_accepted():
    adapter, accepted, rejected = run_file("validos.jsonl")
    assert rejected == [] and adapter.rejected == []
    assert len(accepted) == 8
    # ejemplo de reproducción no simulada conserva su origen
    origins = {(r.observation.data_origin.value, r.observation.is_simulated) for r in accepted}
    assert origins == {("simulation", True), ("replay", False)}


def test_invalid_examples_all_rejected():
    adapter, accepted, rejected = run_file("invalidos.jsonl")
    assert accepted == []
    codes = sorted(r.reason_code for r in rejected) + sorted(r.reason_code for r in adapter.rejected)
    assert sorted(r.reason_code for r in adapter.rejected) == ["INVALID_EVENT", "MALFORMED_JSON"]
    assert set(codes) >= {
        "UNSUPPORTED_VERSION", "OUT_OF_RANGE", "POSITION_SENTINEL", "FUTURE_TIMESTAMP", "STALE",
        "TIMESTAMP_NO_TZ", "INCOHERENT_FIELDS", "SCHEMA_ERROR", "ACOUSTIC_WITH_POSITION",
        "SIMULATION_FLAG_MISMATCH", "UNKNOWN_STATION",
    }
    assert len(rejected) + len(adapter.rejected) == 14
    assert all(isinstance(r, RejectedInput) for r in adapter.rejected)
    assert adapter.rejected[0].raw_reference == "invalidos.jsonl:2"


def test_adapter_handles_weird_lines(tmp_path):
    p = tmp_path / "raro.jsonl"
    p.write_bytes(b"\n# comentario\n[1,2]\nNaN\n\xff\xfe basura\n" + b'{"kind":"x"}\n')
    adapter = ReplayFileAdapter(p)
    assert list(adapter.events()) == []
    assert [r.reason_code for r in adapter.rejected] == ["INVALID_EVENT", "MALFORMED_JSON", "MALFORMED_JSON", "INVALID_EVENT"]


def test_adapter_is_deterministic():
    a = list(ReplayFileAdapter(EXAMPLES / "validos.jsonl").events())
    b = list(ReplayFileAdapter(EXAMPLES / "validos.jsonl").events())
    assert a == b


def test_receiver_adapter_is_abstract_and_requires_authorization():
    assert inspect.isabstract(ReceiverAdapter)
    with pytest.raises(TypeError):
        ReceiverAdapter(ReceptionAuthorization("REF-1", "entidad", "alcance"))  # abstracta

    class Dummy(ReceiverAdapter):
        def events(self):
            return iter(())

        def describe(self):
            return {"adapter": "dummy"}

    with pytest.raises(ValueError):
        Dummy(None)
    with pytest.raises(ValueError):
        Dummy(ReceptionAuthorization(" ", "entidad", "alcance"))
    assert Dummy(ReceptionAuthorization("REF-1", "entidad", "alcance")).describe() == {"adapter": "dummy"}


def test_adapters_module_opens_no_radio_or_network():
    source = inspect.getsource(adapters_module)
    for forbidden in ("import socket", "import serial", "scapy", "pcap", "bluetooth", "requests", "urllib"):
        assert forbidden not in source
