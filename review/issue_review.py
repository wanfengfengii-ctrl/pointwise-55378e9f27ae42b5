"""Sign a whole-window credential over the current sampling cutoff."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observations.journal import BatchJournal
from observations.selection import select_observations
from rules.catalog import ScheduleCatalog
from rules.lookup import get_station_revision

from .archive import ReviewArchive
from .coverage import build_coverage
from .evidence import build_review_row
from .receipt import ReviewBinding, ReviewPage, require_same_issuance, validate_review_window

if TYPE_CHECKING:
    from warehouse import Store


def issue_review(store: Store, page_id: str, station: str, revision: str,
                 start: int, end: int) -> ReviewPage:
    """Fix the current cutoff, the named revision and the whole-window coverage."""
    store.require_key(page_id, 'review id')
    store.require_key(station, 'station')
    store.require_key(revision, 'revision')
    validate_review_window(start, end)
    archive = ReviewArchive(store.connection)
    with store.write():
        original = archive.find_page(page_id)
        if original is not None:
            if not original.credential:
                raise ValueError(f'review {page_id!r} was not signed as a credential')
            require_same_issuance(original, station, revision, start, end)
            return original
        schedule = get_station_revision(ScheduleCatalog(store.connection), station, revision)
        cutoff = BatchJournal(store.connection).latest_cutoff()
        observations = select_observations(BatchJournal(store.connection), station, cutoff, start, end)
        rows = tuple(build_review_row(observation, schedule) for observation in observations)
        coverage = build_coverage(schedule, start, end)
        page = ReviewPage(page_id, ReviewBinding(station, cutoff, revision, start, end), rows, coverage)
        archive.store_page(page)
        return page
