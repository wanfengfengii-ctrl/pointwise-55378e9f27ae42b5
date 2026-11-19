"""Sample station configuration for a local shift exercise."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ranges import ReadingRange
from .registry import Station, StationRegistry

if TYPE_CHECKING:
    from warehouse import Store


DEMO_STATIONS = (
    Station('gull', 'mV', ReadingRange(-50, 50)),
    Station('reef', 'mV', ReadingRange(-100, 100)),
)


def bootstrap_stations(store: Store) -> tuple[Station, ...]:
    registry = StationRegistry(store)
    with store.write():
        registry.initialize()
        return tuple(
            registry.ensure_station(
                sample.code, sample.unit, sample.reading_range.minimum, sample.reading_range.maximum
            )
            for sample in DEMO_STATIONS
        )
