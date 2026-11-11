"""Registro de estaciones FICTICIAS de la simulacion.

Los nodos ``INST-SIM-*`` son abstractos: no tienen coordenadas y este registro
nunca se las asigna.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Optional

from src.contracts import Station, StationStatus, load_default_stations

if TYPE_CHECKING:  # pragma: no cover
    from src.storage.db import Storage


class StationRegistry:
    def __init__(self, stations: Optional[Iterable[Station]] = None, storage: "Optional[Storage]" = None):
        items = list(stations) if stations is not None else load_default_stations()
        self._stations: dict[str, Station] = {s.station_id: s for s in items}
        self._storage = storage
        if storage is not None:
            self.sync()

    def list(self) -> list[Station]:
        return [self._stations[k] for k in sorted(self._stations)]

    def get(self, station_id: str) -> Optional[Station]:
        return self._stations.get(station_id)

    def set_status(self, station_id: str, status: StationStatus, when_utc: datetime) -> Station:
        """Cambia el estado de una estacion con marca temporal (tz-aware)."""
        if station_id not in self._stations:
            raise KeyError(station_id)
        if when_utc.tzinfo is None:
            raise ValueError("when_utc debe incluir zona horaria")
        updated = self._stations[station_id].model_copy(
            update={"status": StationStatus(status), "status_timestamp_utc": when_utc}
        )
        self._stations[station_id] = updated
        if self._storage is not None:
            self._storage.upsert_stations([updated])
        return updated

    def status_map(self) -> dict[str, StationStatus]:
        return {sid: s.status for sid, s in self._stations.items()}

    def with_location(self) -> list[Station]:
        return [s for s in self.list() if s.has_location]

    def without_location(self) -> list[Station]:
        return [s for s in self.list() if not s.has_location]

    def sync(self, storage: "Optional[Storage]" = None) -> None:
        """Escribe el estado actual del registro en el almacen."""
        target = storage or self._storage
        if target is not None:
            target.upsert_stations(self.list())
