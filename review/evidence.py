"""A fixed row carries the rule that actually participated in classification."""

from dataclasses import dataclass

from observations.records import Observation
from rules.lookup import lookup_threshold
from rules.revisions import RuleSource, ScheduleRevision

from .classify import Classification, classify_observation


@dataclass(frozen=True, slots=True)
class ReviewRow:
    observation: Observation
    classification: Classification
    threshold: int | None
    rule_source: RuleSource | None


def build_review_row(observation: Observation, revision: ScheduleRevision) -> ReviewRow:
    reading = observation.reading
    rule = None if reading is None else lookup_threshold(revision, observation.hour)
    threshold = None if rule is None else rule.interval.threshold
    source = None if rule is None else rule.source
    return ReviewRow(observation, classify_observation(reading, threshold), threshold, source)
