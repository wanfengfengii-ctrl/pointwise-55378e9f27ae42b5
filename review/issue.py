"""Freeze a review by binding the catalog and observation journal inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observations.journal import BatchJournal
from observations.selection import select_observations
from rules.catalog import ScheduleCatalog
from rules.lookup import get_station_revision

from .archive import ReviewArchive
from .evidence import build_review_row
from .receipt import ReviewBinding, ReviewPage, require_same_binding, validate_review_window

if TYPE_CHECKING:
    from warehouse import Store


def issue_rows(store: Store, page_id: str, station: str, cutoff: int,
               revision: str, start: int, end: int) -> ReviewPage:
    store.require_key(page_id, 'review id')
    store.require_key(station, 'station')
    store.require_key(revision, 'revision')
    validate_review_window(start, end)
    if type(cutoff) is not int or cutoff < 0:
        raise ValueError('cutoff must be a nonnegative integer')
    binding = ReviewBinding(station, cutoff, revision, start, end)
    archive = ReviewArchive(store.connection)
    with store.write():
        original = archive.find_page(page_id)
        if original is not None:
            if original.credential:
                raise ValueError(f'review {page_id!r} was signed as a credential')
            require_same_binding(original, binding)
            return original
        schedule = get_station_revision(ScheduleCatalog(store.connection), station, revision)
        observations = select_observations(BatchJournal(store.connection), station, cutoff, start, end)
        rows = tuple(build_review_row(observation, schedule) for observation in observations)
        page = ReviewPage(page_id, binding, rows)
        archive.store_page(page)
        return page
