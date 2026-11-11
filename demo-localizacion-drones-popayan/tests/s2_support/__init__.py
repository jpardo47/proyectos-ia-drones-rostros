"""Fabricas y dobles de prueba de S2 (almacen, API, orquestacion). Todo SIMULADO."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.contracts import (
    Alert,
    AuditEvent,
    DataOrigin,
    DecisionRecord,
    DetectionState,
    IngestionResult,
    LocationRole,
    Observation,
    PipelineResult,
    RawEvent,
    RejectedInput,
    ReportedLocation,
    ScenarioResult,
    SensorType,
    Track,
    TrackPoint,
    TruthState,
    load_default_stations,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def make_obs(event_id="E1", station="CIV-01", sensor=SensorType.REMOTE_ID, t=0.0,
             lat=2.45, lon=-76.60, **kw) -> Observation:
    data = dict(
        event_id=event_id, station_id=station, sensor_type=sensor, timestamp_utc=at(t),
        data_origin=DataOrigin.SIMULATION, is_simulated=True, object_id="UAS-SIM-1",
        classification="drone", classifier_score=0.9, latitude=lat, longitude=lon,
        altitude=80.0, altitude_reference="agl", measurement_uncertainty=5.0,
        sensor_quality=0.9, raw_reference="sim:" + event_id,
    )
    if sensor == SensorType.ACOUSTIC:
        data.update(latitude=None, longitude=None, altitude=None, altitude_reference=None)
    data.update(kw)
    return Observation(**data)


def make_ingestion(event_id="E1", with_related=True, **kw) -> IngestionResult:
    obs = make_obs(event_id, **kw)
    rel = []
    if with_related:
        rel = [
            ReportedLocation(role=LocationRole.DRONE, latitude=2.45, longitude=-76.60, altitude=80.0,
                             altitude_reference="agl", detail="reportada"),
            ReportedLocation(role=LocationRole.CONTROL_STATION, latitude=2.44, longitude=-76.61, detail="fixed"),
            ReportedLocation(role=LocationRole.TAKEOFF_POINT, latitude=2.43, longitude=-76.62),
        ]
    return IngestionResult(observation=obs, related_locations=rel)


def make_track(track_id="TRK-1", n_points=3, stations=("CIV-01",), lost=False) -> Track:
    pts = [TrackPoint(timestamp_utc=at(i), latitude=2.45 + i * 0.001, longitude=-76.60,
                      altitude=80.0, altitude_reference="agl", uncertainty_m=5.0,
                      source_event_ids=[f"E{i}"]) for i in range(n_points)]
    return Track(track_id=track_id, object_id="UAS-SIM-1", points=pts, first_seen_utc=at(0),
                 last_seen_utc=at(max(n_points - 1, 0)), station_ids=list(stations),
                 sensor_types=[SensorType.REMOTE_ID], is_lost=lost, is_simulated=True)


def make_decision(track_id="TRK-1", n=1, state=DetectionState.DETECCION_POSIBLE,
                  prev=DetectionState.SIN_OBSERVACION, t=1.0) -> DecisionRecord:
    return DecisionRecord(decision_id=f"DEC-{track_id}-{n}", track_id=track_id, state=state,
                          previous_state=prev, rule_id="R-TEST", reason="Motivo de prueba (simulado).",
                          evidence_event_ids=["E0"], requires_human_review=True, decided_at_utc=at(t),
                          engine_version="test-1", is_simulated=True)


def make_alert(alert_id="ALR-1", track_id="TRK-1") -> Alert:
    return Alert(alert_id=alert_id, track_id=track_id, state=DetectionState.REQUIERE_REVISION,
                 message="Alerta informativa de prueba: requiere revision humana.",
                 created_at_utc=at(2), decision_id="DEC-TRK-1-1", is_simulated=True)


def make_audit(audit_id="AUD-1", subject="TRK-1") -> AuditEvent:
    return AuditEvent(audit_id=audit_id, timestamp_utc=at(1), actor="agent_audit",
                      action="state_change", subject=subject, details={"k": "v"}, engine_version="test-1")


def make_rejected(code="MALFORMED") -> RejectedInput:
    return RejectedInput(station_id="CIV-02", received_at_utc=at(3), stage="ingestion",
                         reason_code=code, reason="Mensaje mal formado.", raw_reference="sim:bad", event_id=None)


def make_pipeline_result(with_alert=True) -> PipelineResult:
    return PipelineResult(
        processed_at_utc=at(5),
        accepted=[make_obs("E0")],
        tracks=[make_track()],
        decisions=[make_decision()],
        alerts=[make_alert()] if with_alert else [],
        audit_events=[make_audit()],
    )


def make_truth() -> list[TruthState]:
    return [TruthState(drone_id="UAS-SIM-1", timestamp_utc=at(i), latitude=2.45 + i * 0.001,
                       longitude=-76.60, altitude_agl_m=80.0, emits_remote_id=True) for i in range(3)]


# ----------------------------- dobles para run_demo ----------------------------


def fake_simulate(scenario: str, seed: int) -> ScenarioResult:
    stations = load_default_stations()
    events = []
    for i in range(6):
        o = make_obs(f"E{i}", t=i * 2.0, lat=2.45 + i * 0.0005)
        events.append(RawEvent(kind="observation", station_id="CIV-01", received_at_utc=at(i * 2.0 + 0.5),
                               payload=o.model_dump(mode="json")))
    events.append(RawEvent(kind="observation", station_id="CIV-02", received_at_utc=at(3.0),
                           payload={"bad": True}))
    events.append(RawEvent(kind="observation", station_id="CIV-01", received_at_utc=at(2.5),
                           payload=make_obs("E1", t=2.0).model_dump(mode="json")))  # duplicado
    events.sort(key=lambda e: e.received_at_utc)
    return ScenarioResult(scenario_id=scenario, seed=seed, description="Escenario de prueba (doble).",
                          start_utc=T0, end_utc=at(15), stations=stations, truth=make_truth(),
                          raw_events=events)


class FakeIngestion:
    name = "fake_ingestion"
    version = "0"

    def ingest(self, event):
        if event.payload.get("bad"):
            return RejectedInput(station_id=event.station_id, received_at_utc=event.received_at_utc,
                                 stage="ingestion", reason_code="MALFORMED", reason="Carga mal formada.")
        obs = Observation.model_validate(event.payload)
        return IngestionResult(observation=obs, related_locations=[
            ReportedLocation(role=LocationRole.CONTROL_STATION, latitude=2.44, longitude=-76.61)])


class FakeValidator:
    name = "fake_validator"
    version = "0"

    def __init__(self):
        self.now_values = []

    def validate(self, result, now_utc):
        self.now_values.append(now_utc)
        return result


class FakePipeline:
    """Acumula puntos; declara perdida si pasan ``lost_after_s`` sin observaciones."""

    def __init__(self, lost_after_s=30.0):
        self.config = SimpleNamespace(lost_after_s=lost_after_s)
        self.calls = []
        self._seen = set()
        self._points = []
        self._last = None
        self._lost = False
        self._first = True

    def process_batch(self, observations, now_utc, station_status=None):
        self.calls.append((list(observations), now_utc, dict(station_status or {})))
        accepted, dups, decisions, alerts, audits = [], [], [], [], []
        for o in observations:
            if o.event_id in self._seen:
                dups.append(o.event_id)
                continue
            self._seen.add(o.event_id)
            accepted.append(o)
            self._points.append(TrackPoint(timestamp_utc=o.timestamp_utc, latitude=o.latitude,
                                           longitude=o.longitude, source_event_ids=[o.event_id]))
            self._last = o.timestamp_utc
            self._lost = False
        if accepted and self._first:
            self._first = False
            decisions.append(make_decision(n=1))
            alerts.append(make_alert())
            audits.append(make_audit())
        if (self._last and not self._lost and not accepted
                and (now_utc - self._last).total_seconds() > self.config.lost_after_s):
            self._lost = True
            decisions.append(make_decision(n=2, state=DetectionState.SEGUIMIENTO_PERDIDO,
                                           prev=DetectionState.DETECCION_POSIBLE, t=(now_utc - T0).total_seconds()))
        tracks = []
        if self._points:
            tracks.append(Track(track_id="TRK-1", object_id="UAS-SIM-1", points=list(self._points),
                                first_seen_utc=self._points[0].timestamp_utc, last_seen_utc=self._last,
                                station_ids=["CIV-01"], sensor_types=[SensorType.REMOTE_ID],
                                is_lost=self._lost, is_simulated=True))
        return PipelineResult(processed_at_utc=now_utc, accepted=accepted, duplicates_dropped=dups,
                              tracks=tracks, decisions=decisions, alerts=alerts, audit_events=audits)
