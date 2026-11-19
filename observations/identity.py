"""Batch identity includes every input position, even equal occurrences."""

from collections.abc import Iterable
from dataclasses import dataclass

from .records import ObservationInput


@dataclass(frozen=True, slots=True)
class BatchIdentity:
    station: str
    unit: str
    rows: tuple[ObservationInput, ...]


def make_batch_identity(station: str, unit: str, rows: Iterable[ObservationInput]) -> BatchIdentity:
    try:
        ordered = tuple(rows)
    except TypeError as error:
        raise ValueError('batch rows must be iterable') from error
    for position, row in enumerate(ordered):
        if not isinstance(row, ObservationInput):
            raise ValueError(f'position {position} must contain an ObservationInput')
        if type(row.hour) is not int:
            raise ValueError(f'position {position} must have an integer hour')
        if row.reading is not None and type(row.reading) is not int:
            raise ValueError(f'position {position} must have an integer reading or None')
    return BatchIdentity(station, unit, ordered)


def require_same_batch(batch_id: str, original: BatchIdentity, requested: BatchIdentity) -> None:
    if original != requested:
        raise ValueError(f'batch {batch_id!r} already has different content')
