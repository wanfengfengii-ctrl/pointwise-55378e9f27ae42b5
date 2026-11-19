"""Aggregate fixed review classifications for a whole-day receipt."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from review.classify import Classification
from review.evidence import ReviewRow


@dataclass(frozen=True, slots=True)
class DayTotals:
    normal: int
    exceeded: int
    unruled: int
    missing: int

    @property
    def row_count(self) -> int:
        return self.normal + self.exceeded + self.unruled + self.missing


def count_classifications(rows: Iterable[ReviewRow]) -> DayTotals:
    counts = Counter(row.classification for row in rows)
    return DayTotals(
        counts[Classification.NORMAL], counts[Classification.EXCEEDED],
        counts[Classification.UNRULED], counts[Classification.MISSING],
    )
