"""Regression package and shared real-SQLite fixture."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from warehouse import ObservationInput, ThresholdInterval, Warehouse


class CommitFault:
    """Deny a single SQL COMMIT at the outer write boundary."""

    def __init__(self):
        self.pending = False
        self.denials = 0

    def arm(self):
        self.pending = True

    def __call__(self, connection):
        if self.pending:
            connection.set_authorizer(self._authorize)

    def _authorize(self, action, operation, _arg, _database, _source):
        if self.pending and action == sqlite3.SQLITE_TRANSACTION and operation == 'COMMIT':
            self.pending = False
            self.denials += 1
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK


class WarehouseTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='rivercape-test-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'warehouse.sqlite'
        self.fault = CommitFault()
        self.db = Warehouse(self.path, before_commit=self.fault)
        self.addCleanup(lambda: self.db.close())
        self.db.register_station('cape', 'mV', -50, 50)

    def reopen(self):
        self.db.close()
        self.db = Warehouse(self.path, before_commit=self.fault)

    def publish(self, publication_id, *intervals, station='cape'):
        return self.db.publish_schedule(publication_id, station, (ThresholdInterval(*row) for row in intervals))

    def ingest(self, batch_id, *rows, station='cape', unit='mV'):
        return self.db.ingest_batch(batch_id, station, unit, (ObservationInput(*row) for row in rows))
