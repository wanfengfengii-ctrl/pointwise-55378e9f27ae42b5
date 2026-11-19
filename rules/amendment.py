"""Apply credential-scoped threshold amendments as ordinary revisions.

An amendment compares the signed page against the station's current head
revision, then republishes the whole effective schedule.  Rules that were
not edited keep their original publication/position provenance; rules set
by the amendment are sourced from the amendment's own publication id at the
zero-based input position of the edit that created them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import TYPE_CHECKING

from review.archive import get_review
from rules.catalog import ScheduleCatalog
from rules.intervals import ThresholdInterval
from rules.lookup import get_station_revision, lookup_threshold
from rules.revisions import PublishedRule, PublicationReceipt, RuleSource, ScheduleRevision

if TYPE_CHECKING:
    from review.receipt import CoverageSegment, ReviewPage
    from warehouse import Store


class AmendmentArchive:
    """Remember every accepted amendment so a replay returns its first receipt."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS amendment_receipts (
                request_id TEXT PRIMARY KEY NOT NULL,
                page_id TEXT NOT NULL,
                edits TEXT NOT NULL
            )
        ''')

    def find_receipt(self, request_id: str) -> tuple[str, str] | None:
        row = self._connection.execute('''
            SELECT page_id, edits FROM amendment_receipts WHERE request_id = ?
        ''', (request_id,)).fetchone()
        return None if row is None else (row['page_id'], row['edits'])

    def store_receipt(self, request_id: str, page_id: str, edits: str) -> None:
        self._connection.execute('''
            INSERT INTO amendment_receipts (request_id, page_id, edits) VALUES (?, ?, ?)
        ''', (request_id, page_id, edits))

    def occupies(self, publication_id: str) -> bool:
        row = self._connection.execute('''
            SELECT 1 FROM amendment_receipts WHERE request_id = ?
        ''', (publication_id,)).fetchone()
        return row is not None


def canonical_edits(edits: tuple[tuple[int, int, int | None], ...]) -> str:
    return json.dumps([[start, end, threshold] for start, end, threshold in edits],
                      ensure_ascii=False, separators=(',', ':'))


def validate_edits(edits: Iterable[tuple], window_start: int,
                   window_end: int) -> tuple[tuple[int, int, int | None], ...]:
    try:
        items = list(edits)
    except TypeError as error:
        raise ValueError('edits must be a finite iterable') from error
    if not items:
        raise ValueError('an amendment needs at least one edit')
    validated: list[tuple[int, int, int | None]] = []
    for position, item in enumerate(items):
        try:
            start, end, threshold = item
        except (TypeError, ValueError) as error:
            raise ValueError(f'edit {position} must be a (start, end, threshold) triple') from error
        if type(start) is not int or type(end) is not int or start >= end:
            raise ValueError(f'edit {position} needs integer endpoints and positive width')
        if start < window_start or end > window_end:
            raise ValueError(f'edit {position} lies outside the review window')
        if threshold is not None and (type(threshold) is not int or threshold < 0):
            raise ValueError(f'edit {position} needs a nonnegative integer threshold or None')
        validated.append((start, end, threshold))
    by_start = sorted(validated, key=lambda edit: edit[0])
    for left, right in zip(by_start, by_start[1:]):
        if right[0] < left[1]:
            raise ValueError('amendment edits must not overlap')
    return tuple(validated)


def _page_value(segment: CoverageSegment) -> tuple[int, str, int] | None:
    if segment.threshold is None:
        return None
    return (segment.threshold, segment.source.publication_id, segment.source.position)


def _head_value(revision: ScheduleRevision, hour: int) -> tuple[int, str, int] | None:
    rule = lookup_threshold(revision, hour)
    if rule is None:
        return None
    return (rule.interval.threshold, rule.source.publication_id, rule.source.position)


def _page_value_at(page: ReviewPage, hour: int) -> tuple[int, str, int] | None:
    for segment in page.coverage:
        if segment.start <= hour < segment.end:
            return _page_value(segment)
    return None


def earliest_conflict(page: ReviewPage, head: ScheduleRevision,
                      edits: tuple[tuple[int, int, int | None], ...]) -> int | None:
    """Return the earliest hour where the page and the head revision disagree."""
    earliest = None
    for start, end, _ in edits:
        points = {start, end}
        for segment in page.coverage:
            if segment.start < end and segment.end > start:
                points.update((max(segment.start, start), min(segment.end, end)))
        for rule in head.rules:
            if rule.interval.start < end and rule.interval.end > start:
                points.update((max(rule.interval.start, start), min(rule.interval.end, end)))
        ordered = sorted(points)
        for left, right in zip(ordered, ordered[1:]):
            if left >= right:
                continue
            if _page_value_at(page, left) != _head_value(head, left):
                if earliest is None or left < earliest:
                    earliest = left
                break
    return earliest


def build_amended_revision(publication_id: str, station: str, head: ScheduleRevision,
                           edits: tuple[tuple[int, int, int | None], ...]) -> ScheduleRevision:
    """Republish the head schedule with the edits applied, merging equal neighbours."""
    boundaries = {edit[0] for edit in edits} | {edit[1] for edit in edits}
    for rule in head.rules:
        boundaries.update((rule.interval.start, rule.interval.end))
    pieces: list[tuple[int, int, tuple[int, RuleSource] | None]] = []
    ordered = sorted(boundaries)
    for left, right in zip(ordered, ordered[1:]):
        if left >= right:
            continue
        edit_position = None
        for position, (start, end, threshold) in enumerate(edits):
            if start <= left < end:
                edit_position = position
                value = None if threshold is None else (threshold, RuleSource(publication_id, position))
                break
        else:
            rule = lookup_threshold(head, left)
            value = None if rule is None else (rule.interval.threshold, rule.source)
        if pieces and pieces[-1][1] == left and pieces[-1][2] == value:
            pieces[-1] = (pieces[-1][0], right, value)
        else:
            pieces.append((left, right, value))
    rules = tuple(
        PublishedRule(ThresholdInterval(start, end, value[0]), value[1])
        for start, end, value in pieces if value is not None
    )
    return ScheduleRevision(publication_id, station, rules)


def storage_positions(revision: ScheduleRevision, publication_id: str) -> tuple[int, ...]:
    """Place each rule so that this publication's own sources point at themselves."""
    own = {rule.source.position for rule in revision.rules
           if rule.source.publication_id == publication_id}
    used = set(own)
    next_free = 0
    positions: list[int] = []
    for rule in revision.rules:
        if rule.source.publication_id == publication_id:
            positions.append(rule.source.position)
            continue
        while next_free in used:
            next_free += 1
        positions.append(next_free)
        used.add(next_free)
    return tuple(positions)


def amend_review(store: Store, request_id: str, page_id: str,
                 edits: Iterable[tuple[int, int, int | None]]) -> PublicationReceipt:
    store.require_key(request_id, 'publication id')
    store.require_key(page_id, 'review id')
    archive = AmendmentArchive(store.connection)
    catalog = ScheduleCatalog(store.connection)
    with store.write():
        page = get_review(store, page_id)
        if not page.credential:
            raise ValueError(f'review {page_id!r} was signed without a whole-window credential')
        validated = validate_edits(edits, page.binding.start, page.binding.end)
        canonical = canonical_edits(validated)
        existing = archive.find_receipt(request_id)
        if existing is not None:
            if existing != (page_id, canonical):
                raise ValueError(f'amendment {request_id!r} already has a different application')
            revision = catalog.find_revision(request_id)
            return PublicationReceipt(revision, request_id)
        if catalog.find_revision(request_id) is not None:
            raise ValueError(f'publication {request_id!r} already belongs to a schedule publication')
        station = page.binding.station
        head_id = catalog.get_head(station)
        head = get_station_revision(catalog, station, head_id)
        conflict = earliest_conflict(page, head, validated)
        if conflict is not None:
            error = ValueError(f'page {page_id!r} disagrees with the current schedule at hour {conflict}')
            error.conflict_hour = conflict
            raise error
        revision = build_amended_revision(request_id, station, head, validated)
        catalog.store_revision(revision, row_positions=storage_positions(revision, request_id))
        catalog.move_head(station, request_id)
        archive.store_receipt(request_id, page_id, canonical)
        return PublicationReceipt(revision, request_id)
