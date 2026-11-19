"""Fixed review identities and their immutable outputs."""

from dataclasses import dataclass
from typing import NamedTuple

from rules.revisions import RuleSource

from .evidence import ReviewRow


@dataclass(frozen=True, slots=True)
class ReviewBinding:
    station: str
    cutoff: int
    revision: str
    start: int
    end: int


class CoverageSegment(NamedTuple):
    """One half-open stretch of a credential window with its effective rule."""

    start: int
    end: int
    threshold: int | None
    source: RuleSource | None


@dataclass(frozen=True, slots=True)
class ReviewPage:
    page_id: str
    binding: ReviewBinding
    rows: tuple[ReviewRow, ...]
    coverage: tuple[CoverageSegment, ...] | None = None

    @property
    def credential(self) -> bool:
        """A page signed by issue_review always carries a whole-window coverage."""
        return self.coverage is not None


def validate_review_window(start: int, end: int) -> None:
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError('a review window needs integer endpoints and positive width')


def require_same_binding(page: ReviewPage, requested: ReviewBinding) -> None:
    if page.binding != requested:
        raise ValueError(f'review {page.page_id!r} already has a different binding')


def require_same_issuance(page: ReviewPage, station: str, revision: str,
                          start: int, end: int) -> None:
    """Replay comparison for issue_review, which does not dictate the cutoff."""
    binding = page.binding
    if (binding.station, binding.revision, binding.start, binding.end) != (station, revision, start, end):
        raise ValueError(f'review {page.page_id!r} already has a different issuance')
