"""Build a whole-window coverage from a revision, including empty stretches."""

from __future__ import annotations

from review.receipt import CoverageSegment
from rules.revisions import ScheduleRevision


def build_coverage(revision: ScheduleRevision, start: int, end: int) -> tuple[CoverageSegment, ...]:
    """Tile ``[start, end)`` with the revision's effective rule for every hour.

    The result is ordered by start, has no gaps or overlaps, and contains a
    segment for hours without a rule (``threshold`` and ``source`` both None).
    """
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError('a coverage window needs integer endpoints and positive width')
    segments: list[CoverageSegment] = []
    cursor = start
    for rule in sorted(revision.rules, key=lambda item: item.interval.start):
        interval = rule.interval
        if interval.end <= start:
            continue
        if interval.start >= end:
            break
        if interval.start > cursor:
            segments.append(CoverageSegment(cursor, interval.start, None, None))
            cursor = interval.start
        if interval.end <= cursor:
            continue
        segments.append(CoverageSegment(cursor, min(interval.end, end),
                                       interval.threshold, rule.source))
        cursor = min(interval.end, end)
        if cursor >= end:
            break
    if cursor < end:
        segments.append(CoverageSegment(cursor, end, None, None))
    return tuple(segments)
