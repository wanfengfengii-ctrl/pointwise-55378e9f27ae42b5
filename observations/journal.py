"""Append-only batches with one global admission order."""

from collections.abc import Iterator
import sqlite3

from .identity import BatchIdentity
from .records import BatchReceipt, Observation, ObservationSource


class BatchJournal:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS batches (
                cutoff INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL UNIQUE,
                station TEXT NOT NULL REFERENCES stations (code),
                unit TEXT NOT NULL
            )
        ''')
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS observation_rows (
                cutoff INTEGER NOT NULL REFERENCES batches (cutoff),
                position INTEGER NOT NULL CHECK (position >= 0),
                hour TEXT NOT NULL,
                reading TEXT,
                PRIMARY KEY (cutoff, position)
            )
        ''')
        self._connection.execute('''
            CREATE INDEX IF NOT EXISTS batches_station_cutoff ON batches (station, cutoff)
        ''')

    @staticmethod
    def _observation(row: sqlite3.Row) -> Observation:
        source = ObservationSource(row['batch_id'], row['cutoff'], row['position'])
        reading = None if row['reading'] is None else int(row['reading'], 16)
        return Observation(int(row['hour'], 16), reading, source)

    def find_batch(self, batch_id: str) -> BatchReceipt | None:
        batch = self._connection.execute('''
            SELECT batch_id, station, unit, cutoff FROM batches WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        if batch is None:
            return None
        rows = self._connection.execute('''
            SELECT b.batch_id, r.cutoff, r.position, r.hour, r.reading
            FROM observation_rows AS r JOIN batches AS b ON b.cutoff = r.cutoff
            WHERE r.cutoff = ? ORDER BY r.position
        ''', (batch['cutoff'],))
        observations = tuple(self._observation(row) for row in rows)
        return BatchReceipt(batch_id, batch['station'], batch['unit'], batch['cutoff'], observations)

    def store_batch(self, batch_id: str, identity: BatchIdentity) -> BatchReceipt:
        cursor = self._connection.execute('''
            INSERT INTO batches (batch_id, station, unit) VALUES (?, ?, ?)
        ''', (batch_id, identity.station, identity.unit))
        cutoff = cursor.lastrowid
        observations = tuple(
            Observation(item.hour, item.reading, ObservationSource(batch_id, cutoff, position))
            for position, item in enumerate(identity.rows)
        )
        self._connection.executemany('''
            INSERT INTO observation_rows (cutoff, position, hour, reading) VALUES (?, ?, ?, ?)
        ''', (
            (cutoff, observation.source.position, hex(observation.hour),
             None if observation.reading is None else hex(observation.reading))
            for observation in observations
        ))
        return BatchReceipt(batch_id, identity.station, identity.unit, cutoff, observations)

    def latest_cutoff(self) -> int:
        return self._connection.execute('SELECT COALESCE(MAX(cutoff), 0) FROM batches').fetchone()[0]

    def iter_station_observations(self, station: str, cutoff: int) -> Iterator[Observation]:
        rows = self._connection.execute('''
            SELECT b.batch_id, r.cutoff, r.position, r.hour, r.reading
            FROM batches AS b JOIN observation_rows AS r ON r.cutoff = b.cutoff
            WHERE b.station = ? AND b.cutoff <= ?
        ''', (station, cutoff))
        for row in rows:
            yield self._observation(row)
