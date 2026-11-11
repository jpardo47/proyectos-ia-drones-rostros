"""Trayectorias de drones VIRTUALES y geometria local (ENU) alrededor del punto
publico de referencia (Parque Caldas).

Coordenadas locales: ``east`` y ``north`` en metros respecto a la referencia;
``agl`` es la altura sobre el terreno. Aproximacion esferica plana local: suficiente
para distancias de hasta ~15 km (error << 0.1 %). Todo es determinista.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from src.contracts.stations_default import POPAYAN_REFERENCE

EARTH_RADIUS_M = 6_371_008.8
REF_LAT = POPAYAN_REFERENCE["latitude"]
REF_LON = POPAYAN_REFERENCE["longitude"]
_COS_REF = math.cos(math.radians(REF_LAT))


def enu_to_latlon(east_m: float, north_m: float) -> tuple[float, float]:
    lat = REF_LAT + math.degrees(north_m / EARTH_RADIUS_M)
    lon = REF_LON + math.degrees(east_m / (EARTH_RADIUS_M * _COS_REF))
    return lat, lon


def latlon_to_enu(lat: float, lon: float) -> tuple[float, float]:
    north = math.radians(lat - REF_LAT) * EARTH_RADIUS_M
    east = math.radians(lon - REF_LON) * EARTH_RADIUS_M * _COS_REF
    return east, north


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


class TrajectorySpec(BaseModel):
    """Trayectoria parametrica de un dron virtual.

    kind: ``line`` (velocidad constante), ``orbit`` (circulo), ``waypoints``
    (tramos rectos a velocidad constante; se detiene en el ultimo punto) o
    ``stationary`` (estacionario / hover).
    """

    kind: Literal["line", "orbit", "waypoints", "stationary"]
    start_en: tuple[float, float] = (0.0, 0.0)          # line / stationary
    velocity_en: tuple[float, float] = (0.0, 0.0)       # line (m/s)
    center_en: tuple[float, float] = (0.0, 0.0)         # orbit
    radius_m: float = 0.0                               # orbit
    speed_mps: float = 0.0                              # orbit / waypoints
    phase_deg: float = 0.0                              # orbit
    waypoints_en: list[tuple[float, float]] = Field(default_factory=list)
    agl_m: float = 100.0

    # -- posicion ---------------------------------------------------------- #
    def position(self, t_s: float) -> tuple[float, float, float]:
        """(east, north, agl) en metros en el instante ``t_s`` desde el inicio."""
        if self.kind == "stationary":
            return self.start_en[0], self.start_en[1], self.agl_m
        if self.kind == "line":
            return (
                self.start_en[0] + self.velocity_en[0] * t_s,
                self.start_en[1] + self.velocity_en[1] * t_s,
                self.agl_m,
            )
        if self.kind == "orbit":
            omega = self.speed_mps / self.radius_m if self.radius_m > 0 else 0.0
            ang = math.radians(self.phase_deg) + omega * t_s
            return (
                self.center_en[0] + self.radius_m * math.cos(ang),
                self.center_en[1] + self.radius_m * math.sin(ang),
                self.agl_m,
            )
        return self._waypoint_position(t_s)

    def _waypoint_position(self, t_s: float) -> tuple[float, float, float]:
        pts = self.waypoints_en
        if not pts:
            return 0.0, 0.0, self.agl_m
        remaining = max(0.0, self.speed_mps) * t_s
        for a, b in zip(pts, pts[1:]):
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if seg <= 0:
                continue
            if remaining <= seg:
                f = remaining / seg
                return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), self.agl_m
            remaining -= seg
        return pts[-1][0], pts[-1][1], self.agl_m

    def velocity(self, t_s: float) -> tuple[float, float]:
        """Velocidad horizontal (vx_east, vy_north) por diferencia finita centrada."""
        h = 0.5
        e1, n1, _ = self.position(max(0.0, t_s - h))
        e2, n2, _ = self.position(t_s + h)
        dt = (t_s + h) - max(0.0, t_s - h)
        return (e2 - e1) / dt, (n2 - n1) / dt

    def speed_and_track(self, t_s: float) -> tuple[float, float]:
        """(velocidad m/s, rumbo en grados 0-360 medido desde el norte)."""
        ve, vn = self.velocity(t_s)
        speed = math.hypot(ve, vn)
        track = (math.degrees(math.atan2(ve, vn)) + 360.0) % 360.0 if speed > 1e-6 else 0.0
        return speed, track


# Constructores de conveniencia ------------------------------------------------


def line(start_en: tuple[float, float], velocity_en: tuple[float, float], agl_m: float = 100.0) -> TrajectorySpec:
    return TrajectorySpec(kind="line", start_en=start_en, velocity_en=velocity_en, agl_m=agl_m)


def orbit(center_en: tuple[float, float], radius_m: float, speed_mps: float,
          agl_m: float = 100.0, phase_deg: float = 0.0) -> TrajectorySpec:
    return TrajectorySpec(kind="orbit", center_en=center_en, radius_m=radius_m,
                          speed_mps=speed_mps, agl_m=agl_m, phase_deg=phase_deg)


def waypoints(points_en: list[tuple[float, float]], speed_mps: float, agl_m: float = 100.0) -> TrajectorySpec:
    return TrajectorySpec(kind="waypoints", waypoints_en=list(points_en), speed_mps=speed_mps, agl_m=agl_m)


def stationary(at_en: tuple[float, float], agl_m: float = 100.0) -> TrajectorySpec:
    return TrajectorySpec(kind="stationary", start_en=at_en, agl_m=agl_m)


def start_point(spec: TrajectorySpec) -> tuple[float, float]:
    e, n, _ = spec.position(0.0)
    return e, n


def destination_en(origin_en: tuple[float, float], distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Punto a ``distance_m`` de ``origin_en`` con rumbo ``bearing_deg`` (0 = norte)."""
    b = math.radians(bearing_deg)
    return origin_en[0] + distance_m * math.sin(b), origin_en[1] + distance_m * math.cos(b)


__all__ = [
    "TrajectorySpec", "line", "orbit", "waypoints", "stationary", "start_point", "destination_en",
    "enu_to_latlon", "latlon_to_enu", "haversine_m", "EARTH_RADIUS_M",
]
