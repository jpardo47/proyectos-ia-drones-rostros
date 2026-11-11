"""Escenarios del simulador multisensor (DATOS SIMULADOS, deterministas por semilla).

``run_scenario`` produce un ``ScenarioResult`` con:
- ``truth``: estado verdadero de los drones virtuales (SEPARADO de lo observado);
- ``raw_events``: lo que las estaciones virtuales reciben (``RawEvent``), ordenado
  por ``received_at_utc``;
- ``stations``: los 7 nodos ficticios (con el estado final tras fallas simuladas).

Parametros de deteccion HIPOTETICOS (ver ``sensors.py`` y ``docs/simulacion.md``):
no demuestran alcance de ningun hardware.
"""
from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.contracts import (
    RawEvent,
    ScenarioResult,
    Station,
    StationStatus,
    TruthState,
    load_default_stations,
)

from . import sensors as sx
from .trajectories import (
    TrajectorySpec,
    destination_en,
    enu_to_latlon,
    latlon_to_enu,
    line,
    orbit,
    start_point,
    stationary,
    waypoints,
)

DEFAULT_START_UTC = datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #


class DroneSpec(BaseModel):
    """Dron VIRTUAL. ``emits_remote_id=False`` -> no emite Remote ID (solo sensores pasivos)."""

    model_config = ConfigDict(extra="forbid")
    drone_id: str
    uas_id: Optional[str] = None
    trajectory: TrajectorySpec
    emits_remote_id: bool = True
    with_operator: bool = True        # incluye ubicacion de la estacion de control en el mensaje
    with_takeoff: bool = True         # incluye punto de despegue en el mensaje
    emits_sound: bool = True
    emits_rf: bool = True
    observable_until_s: Optional[float] = None   # a partir de aqui nadie lo observa (perdida de senal)
    operator_en: Optional[tuple[float, float]] = None   # por defecto, ~40 m del punto de despegue
    takeoff_en: Optional[tuple[float, float]] = None    # por defecto, punto inicial de la trayectoria


class ContradictionSpec(BaseModel):
    """La estacion ``station_id`` reporta Remote ID del dron con una posicion desplazada."""

    model_config = ConfigDict(extra="forbid")
    drone_id: str
    station_id: str
    offset_en: tuple[float, float]


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    seed: int = 42
    duration_s: int = 300
    step_s: float = 1.0
    start_utc: datetime = DEFAULT_START_UTC
    description: str = ""
    drones: list[DroneSpec] = Field(default_factory=list)
    station_failures: dict[str, float] = Field(default_factory=dict)   # station_id -> segundos desde el inicio
    inst_rx_prob: float = 0.8            # recepcion de nodos INST-SIM (independiente de la distancia)
    range_scale: float = 1.0             # multiplicador de los alcances hipoteticos (solo pruebas)
    duplicate_prob: float = 0.0
    duplicate_max_extra: int = 2
    shared_message_ids: bool = False     # True: el mismo broadcast tiene el mismo message_id en todas las estaciones
    malformed_count: int = 0
    tag_object_id: bool = False          # optico/radar etiquetan object_id = uas_id
    contradiction: Optional[ContradictionSpec] = None


# --------------------------------------------------------------------------- #
# Definicion de escenarios
# --------------------------------------------------------------------------- #


def _uas(i: int) -> str:
    return f"SIM-UAS-{i:04d}"


def _drone(i: int, traj: TrajectorySpec, **kw) -> DroneSpec:
    return DroneSpec(drone_id=f"DRN-{i:03d}", uas_id=_uas(i), trajectory=traj, **kw)


def _base_drones() -> list[DroneSpec]:
    return [
        # linea recta, Remote ID completo (operador + despegue)
        _drone(1, line((-1800.0, -300.0), (12.0, 2.5), 120.0),
               operator_en=(-1850.0, -340.0), takeoff_en=(-1800.0, -300.0)),
        # orbita, Remote ID con despegue pero SIN operador
        _drone(2, orbit((300.0, 900.0), 450.0, 9.0, 90.0), with_operator=False),
        # estacionario cerca de CIV-02, sin Remote ID (solo sonido / RF / optico / radar)
        _drone(3, stationary((150.0, -200.0), 60.0), emits_remote_id=False),
    ]


def _sc_basico(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="basico", seed=seed,
        description="Tres drones virtuales: uno con Remote ID completo (operador y despegue), uno con "
                    "despegue sin operador y uno sin Remote ID. Todos los sensores virtuales activos.",
        drones=_base_drones(),
    )


def _sc_sin_remote_id(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="sin_remote_id", seed=seed,
        description="Drones que no emiten Remote ID: solo acustico (sin posicion), RF (sin posicion), "
                    "optico y radar virtuales (con posicion e incertidumbre).",
        drones=[
            _drone(1, waypoints([(-1500, 200), (0, 400), (1200, -300)], 10.0, 80.0), emits_remote_id=False),
            _drone(2, orbit((100.0, 100.0), 300.0, 8.0, 70.0), emits_remote_id=False),
            _drone(3, stationary((200.0, -150.0), 50.0), emits_remote_id=False),
        ],
    )


def _sc_duplicados(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="duplicados", seed=seed, duration_s=180,
        description="El mismo mensaje se entrega mas de una vez (mismo message_id/event_id) y lo reciben "
                    "varias estaciones con el mismo message_id.",
        drones=[
            _drone(1, line((-1200.0, 0.0), (10.0, 1.0), 100.0), operator_en=(-1240.0, -30.0)),
            _drone(2, orbit((200.0, 400.0), 350.0, 8.0, 80.0)),
        ],
        duplicate_prob=0.6, duplicate_max_extra=3, shared_message_ids=True,
    )


def _sc_contradictorio(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="contradictorio", seed=seed,
        description="Dos fuentes reportan el mismo object_id (uas_id) al mismo tiempo con posiciones "
                    "incompatibles: CIV-04 desplaza su Remote ID ~4.3 km respecto de la posicion real.",
        drones=[_drone(1, orbit((250.0, 350.0), 300.0, 8.0, 100.0))],
        contradiction=ContradictionSpec(drone_id="DRN-001", station_id="CIV-04", offset_en=(3500.0, -2500.0)),
        tag_object_id=True,
    )


def _sc_corroborado(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="corroborado", seed=seed,
        description="Un dron sobre el centro: Remote ID de varias estaciones, optico (CIV-02) y radar "
                    "abstracto (INST-SIM-02), tecnicamente independientes y consistentes entre si.",
        drones=[_drone(1, orbit((200.0, 300.0), 300.0, 8.0, 100.0))],
        inst_rx_prob=0.95,
    )


def _sc_perdida_senal(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="perdida_senal", seed=seed,
        description="DRN-001 deja de ser observado a la mitad del escenario (t=150 s); DRN-002 sigue "
                    "observado hasta el final.",
        drones=[
            _drone(1, line((-1500.0, 100.0), (10.0, 0.0), 100.0), observable_until_s=150.0),
            _drone(2, orbit((300.0, 500.0), 400.0, 9.0, 90.0)),
        ],
    )


def _sc_estacion_caida(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="estacion_caida", seed=seed,
        description="CIV-02 pasa a offline a los 150 s y deja de emitir; el estado final queda en "
                    "ScenarioResult.stations.",
        drones=[
            _drone(1, orbit((150.0, 100.0), 500.0, 9.0, 100.0)),
            _drone(2, line((-1500.0, -600.0), (10.0, 3.0), 90.0), emits_remote_id=False),
        ],
        station_failures={"CIV-02": 150.0},
    )


def _sc_malformados(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="malformados", seed=seed,
        description="Trafico normal mas payloads rotos a proposito: campos faltantes, latitud 999, "
                    "timestamp sin zona o futuro, tipos erroneos, acustico con coordenadas.",
        drones=_base_drones()[:2],
        malformed_count=28,
    )


def _sc_sin_estacion_control(seed: int) -> ScenarioConfig:
    return ScenarioConfig(
        name="sin_estacion_control", seed=seed,
        description="Remote ID sin ubicacion de la estacion de control: un dron con punto de despegue "
                    "y otro sin operador ni despegue (valores DESCONOCIDOS, nunca deducidos).",
        drones=[
            _drone(1, line((-1500.0, 200.0), (10.0, 0.0), 100.0), with_operator=False, with_takeoff=True),
            _drone(2, orbit((300.0, 600.0), 350.0, 8.0, 80.0), with_operator=False, with_takeoff=False),
            _drone(3, waypoints([(900, -900), (900, 900), (-300, 900)], 9.0, 110.0),
                   with_operator=False, with_takeoff=False),
        ],
    )


def _sc_rangos(seed: int) -> ScenarioConfig:
    civ02 = next(s for s in load_default_stations() if s.station_id == "CIV-02")
    origin = latlon_to_enu(civ02.latitude, civ02.longitude)
    dists = [100, 500, 1000, 3000, 5000, 10000]
    names = ["100M", "500M", "1KM", "3KM", "5KM", "10KM"]
    drones = []
    for i, (d, nm) in enumerate(zip(dists, names), start=1):
        pos = destination_en(origin, float(d), 30.0 + 60.0 * (i - 1))
        drones.append(DroneSpec(drone_id=f"DRN-{nm}", uas_id=_uas(i), trajectory=stationary(pos, 50.0),
                                with_operator=False, with_takeoff=False))
    return ScenarioConfig(
        name="rangos_100m_10km", seed=seed, duration_s=120,
        description="Seis drones estacionarios a 100 m, 500 m, 1 km, 3 km, 5 km y 10 km de CIV-02. "
                    "Prueba de SOFTWARE (alcances hipoteticos multiplicados x8); no mide el alcance "
                    "de ningun hardware.",
        drones=drones, range_scale=8.0,
    )


_BUILDERS: dict[str, Callable[[int], ScenarioConfig]] = {
    "basico": _sc_basico,
    "sin_remote_id": _sc_sin_remote_id,
    "duplicados": _sc_duplicados,
    "contradictorio": _sc_contradictorio,
    "corroborado": _sc_corroborado,
    "perdida_senal": _sc_perdida_senal,
    "estacion_caida": _sc_estacion_caida,
    "malformados": _sc_malformados,
    "sin_estacion_control": _sc_sin_estacion_control,
    "rangos_100m_10km": _sc_rangos,
}


def list_scenarios() -> list[str]:
    return list(_BUILDERS)


def get_scenario(name: str, seed: int = 42) -> ScenarioConfig:
    if name not in _BUILDERS:
        raise ValueError(f"escenario desconocido: {name!r}. Disponibles: {', '.join(_BUILDERS)}")
    return _BUILDERS[name](seed)


# --------------------------------------------------------------------------- #
# Ejecucion
# --------------------------------------------------------------------------- #


def run_scenario(config: ScenarioConfig) -> ScenarioResult:
    """Ejecuta el escenario de forma determinista (misma config => mismo resultado)."""
    rng = random.Random(config.seed)
    seed = config.seed
    start = config.start_utc
    end = start + timedelta(seconds=config.duration_s)
    base_stations = load_default_stations()
    known = {s.station_id for s in base_stations}
    for sid in config.station_failures:
        if sid not in known:
            raise ValueError(f"estacion desconocida en station_failures: {sid}")
    fail_at = {sid: start + timedelta(seconds=t) for sid, t in config.station_failures.items()}

    stations_out: list[Station] = []
    for st in base_stations:
        if st.station_id in fail_at:
            when = fail_at[st.station_id]
            st = st.model_copy(update={
                "status": StationStatus.OFFLINE,
                "status_timestamp_utc": when,
                "notes": f"{st.notes or ''} [SIMULADO] Pasa a offline a los "
                         f"{config.station_failures[st.station_id]:.0f} s del escenario "
                         f"({when.strftime('%H:%M:%S')} UTC).".strip(),
            })
        stations_out.append(st)

    civ_enu: dict[str, tuple[float, float]] = {
        s.station_id: latlon_to_enu(s.latitude, s.longitude) for s in base_stations if s.has_location
    }
    drone_ix = {d.drone_id: i for i, d in enumerate(config.drones)}
    n_steps = int(config.duration_s / config.step_s)

    truth: list[TruthState] = []
    events: list[RawEvent] = []

    def deliver(kind: str, station_id: str, received: datetime, payload: dict) -> None:
        fa = fail_at.get(station_id)
        if fa is not None and received >= fa:
            return
        events.append(RawEvent(kind=kind, station_id=station_id, received_at_utc=received, payload=payload))
        if config.duplicate_prob > 0 and rng.random() < config.duplicate_prob:
            for _ in range(rng.randint(1, max(1, config.duplicate_max_extra))):
                later = received + timedelta(seconds=rng.uniform(0.2, 3.0))
                if fa is not None and later >= fa:
                    continue
                events.append(RawEvent(kind=kind, station_id=station_id, received_at_utc=later,
                                       payload=json.loads(json.dumps(payload))))

    for k in range(n_steps):
        t = k * config.step_s
        ts = start + timedelta(seconds=t)

        # ---- estado verdadero ------------------------------------------------ #
        state: dict[str, tuple[float, float, float, float, float, bool]] = {}
        for d in config.drones:
            e, n, agl = d.trajectory.position(t)
            observable = d.observable_until_s is None or t < d.observable_until_s
            spd, trk = d.trajectory.speed_and_track(t)
            lat, lon = enu_to_latlon(e, n)
            state[d.drone_id] = (e, n, agl, spd, trk, observable)
            truth.append(TruthState(
                drone_id=d.drone_id, timestamp_utc=ts, latitude=lat, longitude=lon, altitude_agl_m=agl,
                emits_remote_id=bool(d.emits_remote_id and observable),
                emits_sound=bool(d.emits_sound and observable),
            ))

        # ---- observaciones por estacion/sensor ------------------------------- #
        for st in base_stations:
            if st.station_id in fail_at and ts >= fail_at[st.station_id]:
                continue
            pos_st = civ_enu.get(st.station_id)  # None para INST-SIM
            for sensor in st.virtual_sensors:
                model = sx.SENSOR_MODELS[sensor.value]
                every = max(1, round(model.interval_s / config.step_s))
                if k % every != 0:
                    continue
                for j, d in enumerate(config.drones):
                    e, n, agl, spd, trk, observable = state[d.drone_id]
                    if not observable:
                        continue
                    if sensor.value == "remote_id" and not d.emits_remote_id:
                        continue
                    if sensor.value == "acoustic" and not d.emits_sound:
                        continue
                    if sensor.value == "rf" and not d.emits_rf:
                        continue

                    # probabilidad de deteccion / recepcion
                    if pos_st is not None:
                        dist: Optional[float] = math.hypot(math.hypot(e - pos_st[0], n - pos_st[1]), agl)
                        p = sx.detection_probability(model, dist, config.range_scale)
                    else:
                        dist = None
                        p = config.inst_rx_prob  # independiente de la distancia
                    if rng.random() >= p:
                        continue
                    received = ts + timedelta(seconds=sx.latency(model, rng))
                    ref = f"sim://{config.name}/{seed}/{st.station_id}/{sensor.value}/{k:05d}"

                    if sensor.value == "remote_id":
                        rid_e, rid_n = e + rng.gauss(0, sx.RID_GNSS_SIGMA_M), n + rng.gauss(0, sx.RID_GNSS_SIGMA_M)
                        c = config.contradiction
                        if c and c.drone_id == d.drone_id and c.station_id == st.station_id:
                            rid_e += c.offset_en[0]
                            rid_n += c.offset_en[1]
                        lat, lon = enu_to_latlon(rid_e, rid_n)
                        op = None
                        if d.with_operator:
                            op = enu_to_latlon(*(d.operator_en or _near(start_point(d.trajectory), 40.0)))
                        tk = None
                        if d.with_takeoff:
                            tk = enu_to_latlon(*(d.takeoff_en or start_point(d.trajectory)))
                        mid = (f"rid-{seed}-d{j}-{k:05d}" if config.shared_message_ids
                               else f"rid-{seed}-{st.station_id}-d{j}-{k:05d}")
                        payload = sx.build_remote_id_payload(
                            message_id=mid, ts=ts, uas_id=d.uas_id or d.drone_id, lat=lat, lon=lon, agl_m=agl,
                            speed_mps=round(spd, 2), track_deg=round(trk, 1), rng=rng, operator=op, takeoff=tk,
                            operator_id=f"SIM-OPID-{drone_ix[d.drone_id] + 1:04d}",
                        )
                        deliver("remote_id", st.station_id, received, payload)
                        continue

                    eid = f"obs-{seed}-{st.station_id}-{sensor.value}-{k:05d}-{j}"
                    common = dict(event_id=eid, station_id=st.station_id, sensor=sensor.value, ts=ts,
                                  quality=st.data_quality, raw_reference=ref)
                    if sensor.value == "acoustic":
                        payload = sx.build_observation_payload(
                            classifier_score=sx.acoustic_score(dist if dist is not None else 0.0, rng), **common)
                    elif sensor.value == "rf":
                        payload = sx.build_observation_payload(
                            classifier_score=sx.rf_score(dist if dist is not None else 0.0, rng), **common)
                    else:  # optical / radar: posicion con incertidumbre
                        sigma = sx.position_sigma(model, dist)
                        lat, lon = enu_to_latlon(e + rng.gauss(0, sigma), n + rng.gauss(0, sigma))
                        payload = sx.build_observation_payload(
                            object_id=(d.uas_id if config.tag_object_id else None),
                            classifier_score=round(min(0.99, max(0.5, rng.gauss(0.85, 0.05))), 3),
                            lat=lat, lon=lon, agl_m=round(agl + rng.gauss(0, 3.0), 1),
                            uncertainty_m=round(sigma, 1), **common)
                    deliver("observation", st.station_id, received, payload)

    if config.malformed_count > 0:
        _inject_malformed(config, rng, base_stations, events)

    events.sort(key=lambda ev: ev.received_at_utc)
    return ScenarioResult(
        scenario_id=config.name, seed=seed, description=config.description,
        start_utc=start, end_utc=end, stations=stations_out, truth=truth, raw_events=events,
    )


def _near(en: tuple[float, float], dist_m: float) -> tuple[float, float]:
    return en[0] - dist_m * 0.8, en[1] - dist_m * 0.6


def _inject_malformed(config: ScenarioConfig, rng: random.Random, stations: list[Station],
                      events: list[RawEvent]) -> None:
    start = config.start_utc
    ts0 = start + timedelta(seconds=10)
    t_rid = sx.build_remote_id_payload(
        message_id="tmpl-rid", ts=ts0, uas_id=_uas(99), lat=2.4419, lon=-76.6063, agl_m=80.0,
        speed_mps=5.0, track_deg=90.0, rng=rng, operator=(2.4415, -76.6066), takeoff=(2.4416, -76.6065),
        operator_id="SIM-OPID-0099")
    t_obs = sx.build_observation_payload(
        event_id="tmpl-obs", station_id="CIV-01", sensor="acoustic", ts=ts0, classifier_score=0.8,
        quality=0.9, raw_reference="sim://malformados/template")
    n = config.malformed_count
    for i in range(n):
        kind = sx.MALFORMED_KINDS[i % len(sx.MALFORMED_KINDS)]
        ts = start + timedelta(seconds=config.duration_s * (i + 1) / (n + 1))
        st = stations[i % len(stations)]
        raw_kind, payload = sx.make_malformed_payload(kind, t_rid, t_obs, ts)
        if "station_id" in payload:
            payload["station_id"] = st.station_id
        events.append(RawEvent(kind=raw_kind, station_id=st.station_id,
                               received_at_utc=ts + timedelta(seconds=rng.uniform(0.1, 0.5)),
                               payload=payload))


__all__ = [
    "ScenarioConfig", "DroneSpec", "ContradictionSpec", "list_scenarios", "get_scenario",
    "run_scenario", "DEFAULT_START_UTC",
]
