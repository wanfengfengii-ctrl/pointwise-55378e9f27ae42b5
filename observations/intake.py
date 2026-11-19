"""Admit a complete instrument batch against its registered station."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from stations.registry import StationRegistry
from stations.units import require_matching_unit

from .identity import BatchIdentity, make_batch_identity, require_same_batch
from .journal import BatchJournal
from .records import BatchReceipt, ObservationInput

if TYPE_CHECKING:
    from warehouse import Store


def ingest_batch(store: Store, batch_id: str, station: str, unit: str,
                 rows: Iterable[ObservationInput]) -> BatchReceipt:
    store.require_key(batch_id, 'batch id')
    requested = make_batch_identity(station, unit, rows)
    registry = StationRegistry(store)
    journal = BatchJournal(store.connection)
    with store.write():
        configuration = registry.get_station(station)
        require_matching_unit(configuration.unit, unit)
        for position, row in enumerate(requested.rows):
            if row.reading is not None and not configuration.reading_range.contains(row.reading):
                raise ValueError(f'position {position} is outside the registered reading range')
        previous = journal.find_batch(batch_id)
        if previous is not None:
            original = BatchIdentity(previous.station, previous.unit, tuple(
                ObservationInput(observation.hour, observation.reading)
                for observation in previous.observations
            ))
            require_same_batch(batch_id, original, requested)
            return previous
        return journal.store_batch(batch_id, requested)
