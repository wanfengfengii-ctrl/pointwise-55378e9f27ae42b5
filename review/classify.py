"""Mutually exclusive quality classifications for one observation."""

from enum import StrEnum


class Classification(StrEnum):
    NORMAL = 'normal'
    EXCEEDED = 'exceeded'
    UNRULED = 'unruled'
    MISSING = 'missing'


def classify_observation(reading: int | None, threshold: int | None) -> Classification:
    if reading is None:
        return Classification.MISSING
    if threshold is None:
        return Classification.UNRULED
    if reading > threshold:
        return Classification.EXCEEDED
    return Classification.NORMAL
