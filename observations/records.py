"""Values crossing the boundary from the instrument journal to review."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObservationInput:
    hour: int
    reading: int | None


@dataclass(frozen=True, slots=True)
class ObservationSource:
    batch_id: str
    cutoff: int
    position: int


@dataclass(frozen=True, slots=True)
class Observation:
    hour: int
    reading: int | None
    source: ObservationSource


@dataclass(frozen=True, slots=True)
class BatchReceipt:
    batch_id: str
    station: str
    unit: str
    cutoff: int
    observations: tuple[Observation, ...]
