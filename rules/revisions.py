"""Immutable whole publications and the input positions they identify."""

from collections.abc import Iterable
from dataclasses import dataclass

from .intervals import ThresholdInterval, validate_intervals


@dataclass(frozen=True, slots=True)
class RuleSource:
    publication_id: str
    position: int


@dataclass(frozen=True, slots=True)
class PublishedRule:
    interval: ThresholdInterval
    source: RuleSource


@dataclass(frozen=True, slots=True)
class ScheduleRevision:
    publication_id: str
    station: str
    rules: tuple[PublishedRule, ...]


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    revision: ScheduleRevision
    current_head: str


def build_revision(publication_id: str, station: str,
                   intervals: Iterable[ThresholdInterval]) -> ScheduleRevision:
    rules = tuple(
        PublishedRule(interval, RuleSource(publication_id, position))
        for position, interval in validate_intervals(intervals)
    )
    return ScheduleRevision(publication_id, station, rules)


def same_publication(original: ScheduleRevision, requested: ScheduleRevision) -> bool:
    # Each rule retains its input position even though both tuples are in lookup order.
    return original == requested
