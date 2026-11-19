"""Persistent station configuration used by both batch and rule writers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ranges import ReadingRange, validate_reading_range
from .units import validate_unit

if TYPE_CHECKING:
    from warehouse import Store


@dataclass(frozen=True, slots=True)
class Station:
    code: str
    unit: str
    reading_range: ReadingRange


class StationRegistry:
    def __init__(self, store: Store):
        self._store = store
        self._connection = store.connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS stations (
                code TEXT PRIMARY KEY NOT NULL,
                unit TEXT NOT NULL,
                minimum TEXT NOT NULL,
                maximum TEXT NOT NULL
            )
        ''')

    def _find_station(self, code: str) -> Station | None:
        row = self._connection.execute(
            'SELECT code, unit, minimum, maximum FROM stations WHERE code = ?', (code,)
        ).fetchone()
        if row is None:
            return None
        limits = ReadingRange(int(row['minimum'], 16), int(row['maximum'], 16))
        return Station(row['code'], row['unit'], limits)

    def _validated_station(self, code: str, unit: str, minimum: int, maximum: int) -> Station:
        self._store.require_key(code, 'station')
        return Station(code, validate_unit(unit), validate_reading_range(minimum, maximum))

    def _insert_if_missing(self, station: Station) -> None:
        limits = station.reading_range
        self._connection.execute('''
            INSERT INTO stations (code, unit, minimum, maximum) VALUES (?, ?, ?, ?)
            ON CONFLICT (code) DO NOTHING
        ''', (station.code, station.unit, hex(limits.minimum), hex(limits.maximum)))

    def register_station(self, code: str, unit: str, minimum: int, maximum: int) -> Station:
        requested = self._validated_station(code, unit, minimum, maximum)
        with self._store.write():
            self._insert_if_missing(requested)
            stored = self.get_station(code)
            if stored != requested:
                raise ValueError(f'station {code!r} already has a different configuration')
            return stored

    def get_station(self, code: str) -> Station:
        self._store.require_key(code, 'station')
        station = self._find_station(code)
        if station is None:
            raise KeyError(f'unknown station {code!r}')
        return station

    def ensure_station(self, code: str, unit: str, minimum: int, maximum: int) -> Station:
        """Insert a sample only if its code has no registered configuration."""
        self._insert_if_missing(self._validated_station(code, unit, minimum, maximum))
        return self.get_station(code)
