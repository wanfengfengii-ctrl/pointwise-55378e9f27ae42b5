"""Resolve a station's fixed revision and look up a single hour."""

from .catalog import ScheduleCatalog
from .revisions import PublishedRule, ScheduleRevision


def get_station_revision(catalog: ScheduleCatalog, station: str, publication_id: str) -> ScheduleRevision:
    revision = catalog.find_revision(publication_id)
    if revision is None:
        raise KeyError(f'unknown revision {publication_id!r}')
    if revision.station != station:
        raise ValueError(f'revision {publication_id!r} belongs to station {revision.station!r}')
    return revision


def lookup_threshold(revision: ScheduleRevision, hour: int) -> PublishedRule | None:
    if type(hour) is not int:
        raise ValueError('lookup hour must be an integer')
    for rule in revision.rules:
        if hour < rule.interval.start:
            break
        if hour < rule.interval.end:
            return rule
    return None
