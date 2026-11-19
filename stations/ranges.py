"""Integer measurement ranges include both endpoints."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReadingRange:
    minimum: int
    maximum: int

    def contains(self, reading: int) -> bool:
        return type(reading) is int and self.minimum <= reading <= self.maximum


def validate_reading_range(minimum: int, maximum: int) -> ReadingRange:
    if type(minimum) is not int or type(maximum) is not int:
        raise ValueError('reading range endpoints must be integers')
    if minimum > maximum:
        raise ValueError('reading range minimum exceeds maximum')
    return ReadingRange(minimum, maximum)
