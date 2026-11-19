"""Close an aligned day from a fixed review page in one transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from review.archive import get_review

from .archive import DayArchive
from .receipt import DayClose, require_same_page
from .reconcile import reconcile_page_totals, resolve_day_window
from .totals import count_classifications

if TYPE_CHECKING:
    from warehouse import Store


def close_day(store: Store, close_id: str, page_id: str) -> DayClose:
    store.require_key(close_id, 'day close id')
    store.require_key(page_id, 'review id')
    archive = DayArchive(store.connection)
    with store.write():
        original = archive.find_day(close_id)
        if original is not None:
            require_same_page(original, page_id)
            return original
        page = get_review(store, page_id)
        day = resolve_day_window(page)
        totals = count_classifications(page.rows)
        reconcile_page_totals(page, totals)
        close = DayClose(close_id, page_id, page.binding.station, day, totals)
        archive.store_day(close)
        return close
