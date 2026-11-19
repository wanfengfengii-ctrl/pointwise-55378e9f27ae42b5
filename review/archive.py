"""Keep review bindings and ordered evidence independently of current rules."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from observations.records import Observation, ObservationSource
from rules.revisions import RuleSource

from .classify import Classification
from .evidence import ReviewRow
from .receipt import ReviewBinding, ReviewPage

if TYPE_CHECKING:
    from warehouse import Store


class ReviewArchive:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS review_pages (
                page_id TEXT PRIMARY KEY NOT NULL,
                station TEXT NOT NULL,
                cutoff INTEGER NOT NULL CHECK (cutoff >= 0),
                revision TEXT NOT NULL,
                start_hour TEXT NOT NULL,
                end_hour TEXT NOT NULL,
                FOREIGN KEY (station, revision)
                    REFERENCES schedule_revisions (station, publication_id)
            )
        ''')
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS review_rows (
                page_id TEXT NOT NULL REFERENCES review_pages (page_id),
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                batch_id TEXT NOT NULL REFERENCES batches (batch_id),
                batch_cutoff INTEGER NOT NULL,
                batch_position INTEGER NOT NULL,
                hour TEXT NOT NULL,
                reading TEXT,
                classification TEXT NOT NULL,
                threshold TEXT,
                rule_publication TEXT,
                rule_position INTEGER,
                PRIMARY KEY (page_id, ordinal),
                UNIQUE (page_id, batch_id, batch_position),
                FOREIGN KEY (batch_cutoff, batch_position)
                    REFERENCES observation_rows (cutoff, position),
                FOREIGN KEY (rule_publication, rule_position)
                    REFERENCES schedule_rules (publication_id, position),
                CHECK ((threshold IS NULL AND rule_publication IS NULL AND rule_position IS NULL)
                    OR (threshold IS NOT NULL AND rule_publication IS NOT NULL AND rule_position IS NOT NULL))
            )
        ''')

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> ReviewRow:
        observation = Observation(
            int(row['hour'], 16), None if row['reading'] is None else int(row['reading'], 16),
            ObservationSource(row['batch_id'], row['batch_cutoff'], row['batch_position']),
        )
        if row['threshold'] is None:
            return ReviewRow(observation, Classification(row['classification']), None, None)
        source = RuleSource(row['rule_publication'], row['rule_position'])
        return ReviewRow(observation, Classification(row['classification']), int(row['threshold'], 16), source)

    def find_page(self, page_id: str) -> ReviewPage | None:
        header = self._connection.execute('''
            SELECT station, cutoff, revision, start_hour, end_hour FROM review_pages WHERE page_id = ?
        ''', (page_id,)).fetchone()
        if header is None:
            return None
        binding = ReviewBinding(header['station'], header['cutoff'], header['revision'],
                                int(header['start_hour'], 16), int(header['end_hour'], 16))
        rows = self._connection.execute('''
            SELECT batch_id, batch_cutoff, batch_position, hour, reading, classification,
                   threshold, rule_publication, rule_position
            FROM review_rows WHERE page_id = ? ORDER BY ordinal
        ''', (page_id,))
        return ReviewPage(page_id, binding, tuple(self._decode_row(row) for row in rows))

    @staticmethod
    def _encode_row(page_id: str, ordinal: int, row: ReviewRow) -> tuple:
        observation = row.observation
        batch = observation.source
        rule = row.rule_source
        return (
            page_id, ordinal, batch.batch_id, batch.cutoff, batch.position, hex(observation.hour),
            None if observation.reading is None else hex(observation.reading), row.classification.value,
            None if row.threshold is None else hex(row.threshold),
            None if rule is None else rule.publication_id, None if rule is None else rule.position,
        )

    def store_page(self, page: ReviewPage) -> None:
        binding = page.binding
        self._connection.execute('''
            INSERT INTO review_pages (page_id, station, cutoff, revision, start_hour, end_hour)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (page.page_id, binding.station, binding.cutoff, binding.revision,
              hex(binding.start), hex(binding.end)))
        self._connection.executemany('''
            INSERT INTO review_rows (page_id, ordinal, batch_id, batch_cutoff, batch_position,
                                     hour, reading, classification, threshold, rule_publication, rule_position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self._encode_row(page.page_id, ordinal, row) for ordinal, row in enumerate(page.rows)))


def get_review(store: Store, page_id: str) -> ReviewPage:
    store.require_key(page_id, 'review id')
    page = ReviewArchive(store.connection).find_page(page_id)
    if page is None:
        raise KeyError(f'unknown review {page_id!r}')
    return page
