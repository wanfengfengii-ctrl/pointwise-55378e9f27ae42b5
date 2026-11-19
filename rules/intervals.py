"""Half-open integer threshold intervals with preserved input positions."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThresholdInterval:
    start: int
    end: int
    threshold: int


def validate_intervals(intervals: Iterable[ThresholdInterval]) -> tuple[tuple[int, ThresholdInterval], ...]:
    try:
        indexed = list(enumerate(intervals))
    except TypeError as error:
        raise ValueError('schedule intervals must be iterable') from error
    for position, interval in indexed:
        if not isinstance(interval, ThresholdInterval):
            raise ValueError(f'position {position} must contain a ThresholdInterval')
        if type(interval.start) is not int or type(interval.end) is not int or interval.start >= interval.end:
            raise ValueError(f'rule {position} must have integer endpoints and positive width')
        if type(interval.threshold) is not int or interval.threshold < 0:
            raise ValueError(f'rule {position} must have a nonnegative integer threshold')
    indexed.sort(key=lambda item: item[1].start)
    for (left_position, left), (right_position, right) in zip(indexed, indexed[1:]):
        if right.start < left.end:
            raise ValueError(f'rules {left_position} and {right_position} overlap')
    return tuple(indexed)
