"""Reconcile an aligned day and its source rows before signing the close."""

from review.receipt import ReviewPage

from .totals import DayTotals


HOURS_PER_DAY = 24


def resolve_day_window(page: ReviewPage) -> int:
    start = page.binding.start
    end = page.binding.end
    if start % HOURS_PER_DAY != 0 or end != start + HOURS_PER_DAY:
        raise ValueError('a day close requires a full, aligned 24-hour review window')
    return start // HOURS_PER_DAY


def reconcile_page_totals(page: ReviewPage, totals: DayTotals) -> None:
    sources = set()
    for row in page.rows:
        observation = row.observation
        if not page.binding.start <= observation.hour < page.binding.end:
            raise ValueError('review contains an observation outside its day window')
        source = (observation.source.batch_id, observation.source.position)
        if source in sources:
            raise ValueError('review contains a repeated observation source')
        sources.add(source)
    if totals.row_count != len(sources):
        raise ValueError('day counts do not reconcile with the fixed review rows')
