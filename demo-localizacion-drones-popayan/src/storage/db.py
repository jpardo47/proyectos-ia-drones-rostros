"""Persistencia SQLite (stdlib) de la demo de localizacion multisensor (P3).

Todo dato proviene de la SIMULACION salvo lo que un operador ingrese a mano.
El estado verdadero del escenario vive en la tabla aparte ``scenario_truth``
(marcada ``is_simulated = 1``) y nunca se mezcla con las observaciones.

Las consultas son siempre parametrizadas. Una sola conexion protegida por un
cerrojo reentrante: sirve tanto para ``:memory:`` como para archivo, y para los
hilos del servidor de FastAPI.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from src.contracts import (
    Alert,
    AuditEvent,
    DecisionRecord,
    IngestionResult,
    Observation,
    PipelineResult,
    RejectedInput,
    ReportedLocation,
    ReviewStatus,
    Station,
    Track,
    TrackPoint,
    TruthState,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "runtime" / "popayan_demo.sqlite"
STORAGE_VERSION = "storage-1.0"

_TABLES = (
    "stations", "observations", "related_locations", "rejected_inputs", "track_points",
    "tracks", "decisions", "alerts", "audit_events", "scenario_truth", "runs",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
    event_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    is_simulated INTEGER NOT NULL,
    object_id TEXT,
    classification TEXT,
    classifier_score REAL,
    latitude REAL,
    longitude REAL,
    altitude REAL,
    altitude_reference TEXT,
    measurement_uncertainty REAL,
    sensor_quality REAL,
    raw_reference TEXT
);
CREATE INDEX IF NOT EXISTS ix_obs_station ON observations(station_id);
CREATE INDEX IF NOT EXISTS ix_obs_time ON observations(timestamp_utc);
CREATE TABLE IF NOT EXISTS related_locations (
    event_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('drone', 'control_station', 'takeoff_point')),
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude REAL,
    altitude_reference TEXT,
    detail TEXT,
    PRIMARY KEY (event_id, role)
);
CREATE TABLE IF NOT EXISTS rejected_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT,
    received_at_utc TEXT NOT NULL,
    stage TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    raw_reference TEXT,
    event_id TEXT
);
CREATE TABLE IF NOT EXISTS tracks (
    track_id TEXT PRIMARY KEY,
    object_id TEXT,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    station_ids TEXT NOT NULL,
    sensor_types TEXT NOT NULL,
    is_lost INTEGER NOT NULL,
    is_simulated INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS track_points (
    track_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    timestamp_utc TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude REAL,
    altitude_reference TEXT,
    uncertainty_m REAL,
    source_event_ids TEXT NOT NULL,
    PRIMARY KEY (track_id, seq)
);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    state TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dec_track ON decisions(track_id);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    review_status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_truth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL,
    drone_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    altitude_agl_m REAL NOT NULL,
    emits_remote_id INTEGER NOT NULL,
    emits_sound INTEGER NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1 CHECK (is_simulated = 1),
    label TEXT NOT NULL DEFAULT 'SIMULADO: verdad del simulador'
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario TEXT NOT NULL,
    seed INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    is_simulated INTEGER NOT NULL DEFAULT 1,
    summary_json TEXT NOT NULL
);
"""


def _iso(value: datetime) -> str:
    """Formato fijo (UTC, microsegundos) para que el orden de texto = orden temporal."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _enum(value: Any) -> Optional[str]:
    return None if value is None else getattr(value, "value", value)


class Storage:
    """Almacen SQLite. ``db_path=":memory:"`` para pruebas."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    # ------------------------------------------------------------------ base
    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def reset(self) -> None:
        """Vacia todas las tablas (conserva el esquema)."""
        with self._lock:
            for table in _TABLES:
                self._conn.execute(f"DELETE FROM {table}")  # nombres fijos, sin entrada externa
            self._conn.execute("DELETE FROM sqlite_sequence")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple | list = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------- estaciones
    def upsert_stations(self, stations: Iterable[Station]) -> None:
        with self._lock:
            for s in stations:
                self._conn.execute(
                    "INSERT INTO stations(station_id, category, name, status, latitude, longitude, json) "
                    "VALUES (?,?,?,?,?,?,?) ON CONFLICT(station_id) DO UPDATE SET "
                    "category=excluded.category, name=excluded.name, status=excluded.status, "
                    "latitude=excluded.latitude, longitude=excluded.longitude, json=excluded.json",
                    (s.station_id, s.category.value, s.name, s.status.value,
                     s.latitude, s.longitude, s.model_dump_json()),
                )
            self._conn.commit()

    def list_stations(self) -> list[Station]:
        rows = self._query("SELECT json FROM stations ORDER BY station_id")
        return [Station.model_validate_json(r["json"]) for r in rows]

    # ----------------------------------------------------------- observaciones
    def save_ingestion(self, result: IngestionResult) -> None:
        """Guarda la observacion (sin duplicar por ``event_id``) y sus ubicaciones asociadas."""
        o = result.observation
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO observations(event_id, station_id, sensor_type, timestamp_utc, "
                "data_origin, is_simulated, object_id, classification, classifier_score, latitude, "
                "longitude, altitude, altitude_reference, measurement_uncertainty, sensor_quality, "
                "raw_reference) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (o.event_id, o.station_id, o.sensor_type.value, _iso(o.timestamp_utc),
                 o.data_origin.value, int(o.is_simulated), o.object_id, o.classification,
                 o.classifier_score, o.latitude, o.longitude, o.altitude,
                 _enum(o.altitude_reference), o.measurement_uncertainty, o.sensor_quality,
                 o.raw_reference),
            )
            for loc in result.related_locations:
                self._conn.execute(
                    "INSERT OR REPLACE INTO related_locations(event_id, role, latitude, longitude, "
                    "altitude, altitude_reference, detail) VALUES (?,?,?,?,?,?,?)",
                    (o.event_id, loc.role.value, loc.latitude, loc.longitude, loc.altitude,
                     _enum(loc.altitude_reference), loc.detail),
                )
            self._conn.commit()

    @staticmethod
    def _row_to_observation(r: sqlite3.Row) -> Observation:
        data = dict(r)
        data["is_simulated"] = bool(data["is_simulated"])
        data["timestamp_utc"] = _parse(data["timestamp_utc"])
        return Observation.model_validate(data)

    def list_observations(
        self,
        station_id: Optional[str] = None,
        sensor_type: Optional[str] = None,
        desde: Optional[datetime] = None,
        hasta: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Observation]:
        where: list[str] = []
        params: list[Any] = []
        if station_id:
            where.append("station_id = ?")
            params.append(station_id)
        if sensor_type:
            where.append("sensor_type = ?")
            params.append(getattr(sensor_type, "value", sensor_type))
        if desde is not None:
            where.append("timestamp_utc >= ?")
            params.append(_iso(desde))
        if hasta is not None:
            where.append("timestamp_utc <= ?")
            params.append(_iso(hasta))
        sql = "SELECT * FROM observations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp_utc, event_id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [int(limit), int(offset)]
        return [self._row_to_observation(r) for r in self._query(sql, params)]

    def list_related_locations(self, event_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Devuelve dicts ``{event_id, location: ReportedLocation, timestamp_utc}``."""
        sql = ("SELECT rl.*, o.timestamp_utc AS obs_ts FROM related_locations rl "
               "LEFT JOIN observations o ON o.event_id = rl.event_id")
        params: list[Any] = []
        if event_id:
            sql += " WHERE rl.event_id = ?"
            params.append(event_id)
        sql += " ORDER BY obs_ts, rl.event_id, rl.role"
        out = []
        for r in self._query(sql, params):
            loc = ReportedLocation(
                role=r["role"], latitude=r["latitude"], longitude=r["longitude"],
                altitude=r["altitude"], altitude_reference=r["altitude_reference"],
                detail=r["detail"],
            )
            out.append({
                "event_id": r["event_id"],
                "timestamp_utc": _parse(r["obs_ts"]) if r["obs_ts"] else None,
                "location": loc,
            })
        return out

    # ------------------------------------------------------------- rechazados
    def save_rejected(self, rejected: RejectedInput) -> None:
        self._exec(
            "INSERT INTO rejected_inputs(station_id, received_at_utc, stage, reason_code, reason, "
            "raw_reference, event_id) VALUES (?,?,?,?,?,?,?)",
            (rejected.station_id, _iso(rejected.received_at_utc), rejected.stage,
             rejected.reason_code, rejected.reason, rejected.raw_reference, rejected.event_id),
        )

    def list_rejected(self, limit: Optional[int] = None) -> list[RejectedInput]:
        sql = "SELECT * FROM rejected_inputs ORDER BY received_at_utc, id"
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        out = []
        for r in self._query(sql, params):
            out.append(RejectedInput(
                station_id=r["station_id"], received_at_utc=_parse(r["received_at_utc"]),
                stage=r["stage"], reason_code=r["reason_code"], reason=r["reason"],
                raw_reference=r["raw_reference"], event_id=r["event_id"],
            ))
        return out

    # -------------------------------------------------------------- pipeline
    def _upsert_track(self, t: Track) -> None:
        self._conn.execute(
            "INSERT INTO tracks(track_id, object_id, first_seen_utc, last_seen_utc, station_ids, "
            "sensor_types, is_lost, is_simulated) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(track_id) DO UPDATE SET object_id=excluded.object_id, "
            "first_seen_utc=excluded.first_seen_utc, last_seen_utc=excluded.last_seen_utc, "
            "station_ids=excluded.station_ids, sensor_types=excluded.sensor_types, "
            "is_lost=excluded.is_lost, is_simulated=excluded.is_simulated",
            (t.track_id, t.object_id, _iso(t.first_seen_utc), _iso(t.last_seen_utc),
             json.dumps(t.station_ids), json.dumps([s.value for s in t.sensor_types]),
             int(t.is_lost), int(t.is_simulated)),
        )
        self._conn.execute("DELETE FROM track_points WHERE track_id = ?", (t.track_id,))
        for i, p in enumerate(t.points):
            self._conn.execute(
                "INSERT INTO track_points(track_id, seq, timestamp_utc, latitude, longitude, altitude, "
                "altitude_reference, uncertainty_m, source_event_ids) VALUES (?,?,?,?,?,?,?,?,?)",
                (t.track_id, i, _iso(p.timestamp_utc), p.latitude, p.longitude, p.altitude,
                 _enum(p.altitude_reference), p.uncertainty_m, json.dumps(p.source_event_ids)),
            )

    def save_pipeline_result(self, result: PipelineResult) -> None:
        """Upsert de tracks (reemplaza puntos); inserta decisiones, alertas y auditoria sin duplicar.

        Las alertas ya existentes NO se sobrescriben (se conserva su revision humana).
        Las observaciones aceptadas se guardan si aun no estaban; los rechazados se registran.
        """
        with self._lock:
            for t in result.tracks:
                self._upsert_track(t)
            for d in result.decisions:
                self._conn.execute(
                    "INSERT OR IGNORE INTO decisions(decision_id, track_id, state, previous_state, "
                    "rule_id, reason, decided_at_utc, json) VALUES (?,?,?,?,?,?,?,?)",
                    (d.decision_id, d.track_id, d.state.value, d.previous_state.value, d.rule_id,
                     d.reason, _iso(d.decided_at_utc), d.model_dump_json()),
                )
            for a in result.alerts:
                self._conn.execute(
                    "INSERT OR IGNORE INTO alerts(alert_id, track_id, review_status, created_at_utc, json) "
                    "VALUES (?,?,?,?,?)",
                    (a.alert_id, a.track_id, a.review_status.value, _iso(a.created_at_utc),
                     a.model_dump_json()),
                )
            for e in result.audit_events:
                self._insert_audit(e)
            for o in result.accepted:
                self._conn.execute(
                    "INSERT OR IGNORE INTO observations(event_id, station_id, sensor_type, timestamp_utc, "
                    "data_origin, is_simulated, object_id, classification, classifier_score, latitude, "
                    "longitude, altitude, altitude_reference, measurement_uncertainty, sensor_quality, "
                    "raw_reference) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (o.event_id, o.station_id, o.sensor_type.value, _iso(o.timestamp_utc),
                     o.data_origin.value, int(o.is_simulated), o.object_id, o.classification,
                     o.classifier_score, o.latitude, o.longitude, o.altitude,
                     _enum(o.altitude_reference), o.measurement_uncertainty, o.sensor_quality,
                     o.raw_reference),
                )
            self._conn.commit()

    def _insert_audit(self, e: AuditEvent) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO audit_events(audit_id, timestamp_utc, actor, action, subject, json) "
            "VALUES (?,?,?,?,?,?)",
            (e.audit_id, _iso(e.timestamp_utc), e.actor, e.action, e.subject, e.model_dump_json()),
        )

    # ----------------------------------------------------------------- tracks
    def _track_from_row(self, r: sqlite3.Row, points: list[TrackPoint]) -> Track:
        return Track(
            track_id=r["track_id"], object_id=r["object_id"], points=points,
            first_seen_utc=_parse(r["first_seen_utc"]), last_seen_utc=_parse(r["last_seen_utc"]),
            station_ids=json.loads(r["station_ids"]), sensor_types=json.loads(r["sensor_types"]),
            is_lost=bool(r["is_lost"]), is_simulated=bool(r["is_simulated"]),
        )

    def _points(self, track_id: str) -> list[TrackPoint]:
        rows = self._query("SELECT * FROM track_points WHERE track_id = ? ORDER BY seq", (track_id,))
        return [TrackPoint(
            timestamp_utc=_parse(p["timestamp_utc"]), latitude=p["latitude"], longitude=p["longitude"],
            altitude=p["altitude"], altitude_reference=p["altitude_reference"],
            uncertainty_m=p["uncertainty_m"], source_event_ids=json.loads(p["source_event_ids"]),
        ) for p in rows]

    def list_tracks(self) -> list[Track]:
        rows = self._query("SELECT * FROM tracks ORDER BY first_seen_utc, track_id")
        return [self._track_from_row(r, self._points(r["track_id"])) for r in rows]

    def get_track(self, track_id: str) -> Optional[Track]:
        rows = self._query("SELECT * FROM tracks WHERE track_id = ?", (track_id,))
        if not rows:
            return None
        return self._track_from_row(rows[0], self._points(track_id))

    # ------------------------------------------------------------- decisiones
    def list_decisions(self, track_id: Optional[str] = None) -> list[DecisionRecord]:
        sql = "SELECT json FROM decisions"
        params: list[Any] = []
        if track_id:
            sql += " WHERE track_id = ?"
            params.append(track_id)
        sql += " ORDER BY decided_at_utc, decision_id"
        return [DecisionRecord.model_validate_json(r["json"]) for r in self._query(sql, params)]

    def latest_decisions(self) -> dict[str, DecisionRecord]:
        """Ultima decision por track (por fecha y, en empate, el ultimo insertado)."""
        out: dict[str, DecisionRecord] = {}
        for d in self.list_decisions():
            out[d.track_id] = d
        return out

    # ---------------------------------------------------------------- alertas
    def list_alerts(self, review_status: Optional[str] = None) -> list[Alert]:
        sql = "SELECT json FROM alerts"
        params: list[Any] = []
        if review_status:
            sql += " WHERE review_status = ?"
            params.append(getattr(review_status, "value", review_status))
        sql += " ORDER BY created_at_utc, alert_id"
        return [Alert.model_validate_json(r["json"]) for r in self._query(sql, params)]

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        rows = self._query("SELECT json FROM alerts WHERE alert_id = ?", (alert_id,))
        return Alert.model_validate_json(rows[0]["json"]) if rows else None

    def review_alert(
        self,
        alert_id: str,
        status: ReviewStatus,
        reviewer: str,
        note: Optional[str] = None,
        when_utc: Optional[datetime] = None,
    ) -> Alert:
        """Registra la revision humana de una alerta y un ``AuditEvent`` del operador."""
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ValueError("Debe indicarse quien revisa la alerta.")
        status = ReviewStatus(status)
        when = when_utc or datetime.now(timezone.utc)
        with self._lock:
            alert = self.get_alert(alert_id)
            if alert is None:
                raise KeyError(alert_id)
            updated = alert.model_copy(update={
                "review_status": status, "reviewed_by": reviewer,
                "reviewed_at_utc": when, "review_note": note,
            })
            self._conn.execute(
                "UPDATE alerts SET review_status = ?, json = ? WHERE alert_id = ?",
                (status.value, updated.model_dump_json(), alert_id),
            )
            digest = hashlib.sha1(f"{alert_id}|{status.value}|{_iso(when)}|{reviewer}".encode()).hexdigest()[:12]
            self._insert_audit(AuditEvent(
                audit_id=f"AUD-REV-{digest}",
                timestamp_utc=when,
                actor=f"operador:{reviewer}",
                action="alert_reviewed",
                subject=alert_id,
                details={"status": status.value, "note": note, "track_id": alert.track_id,
                         "previous_status": alert.review_status.value},
                engine_version=STORAGE_VERSION,
            ))
            self._conn.commit()
        return updated

    # -------------------------------------------------------------- auditoria
    def list_audit(self, subject: Optional[str] = None, limit: Optional[int] = None) -> list[AuditEvent]:
        sql = "SELECT json FROM audit_events"
        params: list[Any] = []
        if subject:
            sql += " WHERE subject = ?"
            params.append(subject)
        sql += " ORDER BY timestamp_utc, audit_id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [AuditEvent.model_validate_json(r["json"]) for r in self._query(sql, params)]

    # ------------------------------------------------------------------ truth
    def save_truth(self, scenario_id: str, truth: Iterable[TruthState]) -> None:
        """Estado verdadero del escenario (SIMULADO). Reemplaza el de ese escenario."""
        with self._lock:
            self._conn.execute("DELETE FROM scenario_truth WHERE scenario_id = ?", (scenario_id,))
            for t in truth:
                self._conn.execute(
                    "INSERT INTO scenario_truth(scenario_id, drone_id, timestamp_utc, latitude, longitude, "
                    "altitude_agl_m, emits_remote_id, emits_sound) VALUES (?,?,?,?,?,?,?,?)",
                    (scenario_id, t.drone_id, _iso(t.timestamp_utc), t.latitude, t.longitude,
                     t.altitude_agl_m, int(t.emits_remote_id), int(t.emits_sound)),
                )
            self._conn.commit()

    def list_truth(self, scenario_id: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM scenario_truth"
        params: list[Any] = []
        if scenario_id:
            sql += " WHERE scenario_id = ?"
            params.append(scenario_id)
        sql += " ORDER BY drone_id, timestamp_utc"
        out = []
        for r in self._query(sql, params):
            out.append({
                "scenario_id": r["scenario_id"], "drone_id": r["drone_id"],
                "timestamp_utc": _parse(r["timestamp_utc"]), "latitude": r["latitude"],
                "longitude": r["longitude"], "altitude_agl_m": r["altitude_agl_m"],
                "emits_remote_id": bool(r["emits_remote_id"]), "emits_sound": bool(r["emits_sound"]),
                "is_simulated": True, "label": r["label"],
            })
        return out

    # ------------------------------------------------------------------- runs
    def save_run(self, scenario: str, seed: int, summary: dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO runs(scenario, seed, created_at_utc, summary_json) VALUES (?,?,?,?)",
                (scenario, int(seed), _iso(datetime.now(timezone.utc)), json.dumps(summary, default=str)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_runs(self) -> list[dict[str, Any]]:
        return [
            {"run_id": r["run_id"], "scenario": r["scenario"], "seed": r["seed"],
             "created_at_utc": r["created_at_utc"], "is_simulated": True,
             "summary": json.loads(r["summary_json"])}
            for r in self._query("SELECT * FROM runs ORDER BY run_id")
        ]

    # ----------------------------------------------------------------- conteos
    def counts(self) -> dict[str, int]:
        return {
            t: int(self._query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"])  # nombres fijos
            for t in _TABLES
        }
