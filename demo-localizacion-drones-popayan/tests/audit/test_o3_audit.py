"""Tests del agent_audit y de la trazabilidad del pipeline."""
from __future__ import annotations

import json

from src.audit.agent_audit import AuditAgent
from src.contracts import SensorType as ST
from src.decision_agents.pipeline import ENGINE_VERSION, OperationalPipeline
from tests.decision_agents.o3_factories import LAT0, LON0, obs, offset, t


def _run():
    p = OperationalPipeline()
    r = p.process_batch(
        [obs("rid-1"), obs("rid-1"),
         obs("rad-1", sensor=ST.RADAR, station="EST-SIM-02", object_id=None,
             pos=offset(LAT0, LON0, north_m=10)),
         obs("old", at=-500)],
        now_utc=t(1),
    )
    return p, r


def test_audit_records_each_step():
    _, r = _run()
    actions = [a.action for a in r.audit_events]
    assert actions[0] == "lote_recibido" and actions[-1] == "lote_procesado"
    for needed in ("duplicado_descartado", "observacion_rechazada", "observacion_aceptada",
                   "track_creado", "observacion_asociada", "decision", "alerta_informativa"):
        assert needed in actions, needed
    assert all(a.engine_version == ENGINE_VERSION for a in r.audit_events)
    first = r.audit_events[0].details
    assert first["engine_version"] == ENGINE_VERSION and first["config_fingerprint"]
    assert "agent_correlator" in first["agentes"] and "agent_alerts" in first["agentes"]
    decision_evt = next(a for a in r.audit_events if a.action == "decision")
    assert decision_evt.details["rule_id"] == "R-CORR-01"
    assert decision_evt.details["evidence_event_ids"] == ["rad-1", "rid-1"]
    assert len({a.audit_id for a in r.audit_events}) == len(r.audit_events)


def test_audit_ids_deterministic():
    _, r1 = _run()
    _, r2 = _run()
    assert [a.audit_id for a in r1.audit_events] == [a.audit_id for a in r2.audit_events]


def test_export_jsonl(tmp_path):
    p, r = _run()
    out = p.export_audit_jsonl(tmp_path / "audit" / "o3.jsonl")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(r.audit_events)
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["action"] == "lote_recibido"
    assert all(set(x) >= {"audit_id", "timestamp_utc", "actor", "action", "subject", "details",
                          "engine_version"} for x in parsed)
    assert AuditAgent.to_jsonl(r.audit_events) == out.read_text(encoding="utf-8")


def test_drain_returns_only_new_events():
    a = AuditAgent("v-test")
    a.record(t(0), "x", "uno", "s")
    assert [e.action for e in a.drain()] == ["uno"]
    a.record(t(1), "x", "dos", "s")
    assert [e.action for e in a.drain()] == ["dos"]
    assert [e.action for e in a.history] == ["uno", "dos"]
