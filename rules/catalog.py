"""Persist immutable revisions and the current publication for each station."""

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
                PRIMARY KEY (publication_id, position)
            )
        ''')
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS schedule_heads (
                station TEXT PRIMARY KEY NOT NULL,
                publication_id TEXT NOT NULL,
                FOREIGN KEY (station, publication_id)
                    REFERENCES schedule_revisions (station, publication_id)
            )
        ''')

    def find_revision(self, publication_id: str) -> ScheduleRevision | None:
        header = self._connection.execute('''
            SELECT station FROM schedule_revisions WHERE publication_id = ?
        ''', (publication_id,)).fetchone()
        if header is None:
            return None
        rows = self._connection.execute('''
            SELECT position, start_hour, end_hour, threshold
            FROM schedule_rules WHERE publication_id = ?
        ''', (publication_id,))
        rules = [
            PublishedRule(
                ThresholdInterval(int(row['start_hour'], 16), int(row['end_hour'], 16),
                                  int(row['threshold'], 16)),
                RuleSource(publication_id, row['position']),
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

    def store_revision(self, revision: ScheduleRevision) -> None:
        self._connection.execute('''
            INSERT INTO schedule_revisions (publication_id, station) VALUES (?, ?)
        ''', (revision.publication_id, revision.station))
        self._connection.executemany('''
            INSERT INTO schedule_rules (publication_id, position, start_hour, end_hour, threshold)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            (revision.publication_id, rule.source.position, hex(rule.interval.start),
             hex(rule.interval.end), hex(rule.interval.threshold))
            for rule in revision.rules
        ))

    def move_head(self, station: str, publication_id: str) -> None:
        self._connection.execute('''
            INSERT INTO schedule_heads (station, publication_id) VALUES (?, ?)
            ON CONFLICT (station) DO UPDATE SET publication_id = excluded.publication_id
        ''', (station, publication_id))
