"""Persist immutable revisions and the current publication for each station.

A revision stores its effective rules together with the publication and
position that each rule actually came from.  Ordinary publications take
their own input positions; amended revisions may carry rules inherited
from earlier publications, so the provenance is stored explicitly.
"""

import sqlite3

from .intervals import ThresholdInterval
from .revisions import PublishedRule, RuleSource, ScheduleRevision


class ScheduleCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS schedule_revisions (
                publication_id TEXT PRIMARY KEY NOT NULL,
                station TEXT NOT NULL REFERENCES stations (code),
                UNIQUE (station, publication_id)
            )
        ''')
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS schedule_rules (
                publication_id TEXT NOT NULL REFERENCES schedule_revisions (publication_id),
                position INTEGER NOT NULL CHECK (position >= 0),
                start_hour TEXT NOT NULL,
                end_hour TEXT NOT NULL,
                threshold TEXT NOT NULL,
                source_publication TEXT,
                source_position INTEGER,
                PRIMARY KEY (publication_id, position)
            )
        ''')
        self._ensure_rule_columns()
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS schedule_heads (
                station TEXT PRIMARY KEY NOT NULL,
                publication_id TEXT NOT NULL,
                FOREIGN KEY (station, publication_id)
                    REFERENCES schedule_revisions (station, publication_id)
            )
        ''')

    def _columns(self, table: str) -> set[str]:
        return {row['name'] for row in self._connection.execute(f'PRAGMA table_info({table})')}

    def _ensure_rule_columns(self) -> None:
        """Upgrade a catalog created before explicit rule provenance existed."""
        existing = self._columns('schedule_rules')
        if 'source_publication' not in existing:
            self._connection.execute('ALTER TABLE schedule_rules ADD COLUMN source_publication TEXT')
        if 'source_position' not in existing:
            self._connection.execute('ALTER TABLE schedule_rules ADD COLUMN source_position INTEGER')
        self._connection.execute('''
            UPDATE schedule_rules SET source_publication = publication_id
            WHERE source_publication IS NULL
        ''')
        self._connection.execute('''
            UPDATE schedule_rules SET source_position = position
            WHERE source_position IS NULL
        ''')

    def find_revision(self, publication_id: str) -> ScheduleRevision | None:
        header = self._connection.execute('''
            SELECT station FROM schedule_revisions WHERE publication_id = ?
        ''', (publication_id,)).fetchone()
        if header is None:
            return None
        rows = self._connection.execute('''
            SELECT position, start_hour, end_hour, threshold, source_publication, source_position
            FROM schedule_rules WHERE publication_id = ?
        ''', (publication_id,))
        rules = [
            PublishedRule(
                ThresholdInterval(int(row['start_hour'], 16), int(row['end_hour'], 16),
                                  int(row['threshold'], 16)),
                RuleSource(
                    row['source_publication'] if row['source_publication'] is not None
                    else publication_id,
                    row['source_position'] if row['source_position'] is not None
                    else row['position'],
                ),
            )
            for row in rows
        ]
        rules.sort(key=lambda rule: rule.interval.start)
        return ScheduleRevision(publication_id, header['station'], tuple(rules))

    def get_head(self, station: str) -> str | None:
        row = self._connection.execute('''
            SELECT publication_id FROM schedule_heads WHERE station = ?
        ''', (station,)).fetchone()
        return None if row is None else row['publication_id']

    def store_revision(self, revision: ScheduleRevision,
                       row_positions: int | tuple[int, ...] | None = None) -> None:
        """Insert the revision's effective rules under the given storage positions.

        ``row_positions`` aligns one-to-one with ``revision.rules``; ordinary
        publications keep each rule at its own source position.
        """
        if row_positions is None:
            positions = tuple(rule.source.position for rule in revision.rules)
        elif type(row_positions) is int:
            positions = tuple(range(row_positions, row_positions + len(revision.rules)))
        else:
            positions = tuple(row_positions)
        if len(positions) != len(revision.rules):
            raise ValueError('a storage position is required for every rule')
        self._connection.execute('''
            INSERT INTO schedule_revisions (publication_id, station) VALUES (?, ?)
        ''', (revision.publication_id, revision.station))
        self._connection.executemany('''
            INSERT INTO schedule_rules (publication_id, position, start_hour, end_hour, threshold,
                                        source_publication, source_position)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            (revision.publication_id, position, hex(rule.interval.start),
             hex(rule.interval.end), hex(rule.interval.threshold),
             rule.source.publication_id, rule.source.position)
            for position, rule in zip(positions, revision.rules)
        ))

    def move_head(self, station: str, publication_id: str) -> None:
        self._connection.execute('''
            INSERT INTO schedule_heads (station, publication_id) VALUES (?, ?)
            ON CONFLICT (station) DO UPDATE SET publication_id = excluded.publication_id
        ''', (station, publication_id))
