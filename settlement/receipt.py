"""The fixed station-day receipt refers to a single review page."""

from dataclasses import dataclass

from .totals import DayTotals


@dataclass(frozen=True, slots=True)
class DayClose:
    close_id: str
    page_id: str
    station: str
    day: int
    totals: DayTotals


def require_same_page(close: DayClose, page_id: str) -> None:
    if close.page_id != page_id:
        raise ValueError(f'day close {close.close_id!r} already references a different review')
