"""Fixed review identities and their immutable outputs."""

from dataclasses import dataclass

from .evidence import ReviewRow


@dataclass(frozen=True, slots=True)
class ReviewBinding:
    station: str
    cutoff: int
    revision: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ReviewPage:
    page_id: str
    binding: ReviewBinding
    rows: tuple[ReviewRow, ...]


def validate_review_window(start: int, end: int) -> None:
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError('a review window needs integer endpoints and positive width')


def require_same_binding(page: ReviewPage, requested: ReviewBinding) -> None:
    if page.binding != requested:
        raise ValueError(f'review {page.page_id!r} already has a different binding')
