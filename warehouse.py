"""Connection ownership, public warehouse operations and the local CLI."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from observations.intake import ingest_batch
from observations.journal import BatchJournal
from observations.records import ObservationInput as ObservationInput
from observations.selection import select_observations
from review.archive import ReviewArchive, get_review
from review.issue import issue_rows
from review.receipt import validate_review_window
from rules.catalog import ScheduleCatalog
from rules.intervals import ThresholdInterval as ThresholdInterval
from rules.lookup import get_station_revision, lookup_threshold
from rules.publish import publish_schedule
from settlement.archive import DayArchive, get_day
from settlement.close_day import close_day
from stations.bootstrap import bootstrap_stations
from stations.registry import StationRegistry


class Store:
    def __init__(self, connection, before_commit=None):
        self.connection = connection
        self._before_commit = before_commit

    @staticmethod
    def require_key(value, label):
        if not isinstance(value, str) or not value or value != value.strip() or '\x00' in value:
            raise ValueError(f'{label} must be a nonempty label without surrounding whitespace')

    @contextmanager
    def write(self):
        """Serialize a business write and roll it back on a pre-commit error."""
        connection = self.connection
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            if self._before_commit is not None:
                self._before_commit(connection)
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


class Warehouse:
    """Open a warehouse file or a SQLite memory database on one connection."""

    def __init__(self, path, *, before_commit=None):
        connection = sqlite3.connect(path, isolation_level=None, cached_statements=0)
        connection.row_factory = sqlite3.Row
        self._store = Store(connection, before_commit)
        self._stations = StationRegistry(self._store)
        self._batches = BatchJournal(connection)
        self._catalog = ScheduleCatalog(connection)
        try:
            connection.execute('PRAGMA foreign_keys = ON')
            with self._store.write():
                self._stations.initialize()
                self._batches.initialize()
                self._catalog.initialize()
                ReviewArchive(connection).initialize()
                DayArchive(connection).initialize()
        except BaseException:
            connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._store.connection.close()

    def bootstrap_stations(self):
        return bootstrap_stations(self._store)

    def register_station(self, code, unit, minimum, maximum):
        return self._stations.register_station(code, unit, minimum, maximum)

    def get_station(self, code):
        return self._stations.get_station(code)

    def ingest_batch(self, batch_id, station, unit, rows):
        return ingest_batch(self._store, batch_id, station, unit, rows)

    def get_batch(self, batch_id):
        self._store.require_key(batch_id, 'batch id')
        receipt = self._batches.find_batch(batch_id)
        if receipt is None:
            raise KeyError(f'unknown batch {batch_id!r}')
        return receipt

    def latest_cutoff(self):
        return self._batches.latest_cutoff()

    def list_observations(self, station, cutoff, start, end):
        self.get_station(station)
        validate_review_window(start, end)
        return select_observations(self._batches, station, cutoff, start, end)

    def publish_schedule(self, publication_id, station, intervals):
        return publish_schedule(self._store, publication_id, station, intervals)

    def get_head(self, station):
        self.get_station(station)
        return self._catalog.get_head(station)

    def get_revision(self, station, revision):
        self._store.require_key(station, 'station')
        self._store.require_key(revision, 'revision')
        return get_station_revision(self._catalog, station, revision)

    def threshold_at(self, station, revision, hour):
        return lookup_threshold(self.get_revision(station, revision), hour)

    def issue_rows(self, page_id, station, cutoff, revision, start, end):
        return issue_rows(self._store, page_id, station, cutoff, revision, start, end)

    def get_review(self, page_id):
        return get_review(self._store, page_id)

    def close_day(self, close_id, page_id):
        return close_day(self._store, close_id, page_id)

    def get_day(self, close_id):
        return get_day(self._store, close_id)


def _page_rows(page):
    rows = []
    for row in page.rows:
        source = row.rule_source
        rows.append([
            row.observation.hour,
            row.observation.reading,
            row.classification.value,
            row.threshold,
            [source.publication_id, source.position] if source is not None else None,
        ])
    return rows


def _run_demo(path):
    inputs = [[1, 10], [2, 11], [3, 11], [4, None]]
    old_rules = [[1, 3, 10]]
    new_rules = [[2, 3, 12]]
    with Warehouse(path) as db:
        db.bootstrap_stations()
        db.register_station('cape', 'mV', -50, 50)
        db.publish_schedule('A', 'cape', map(lambda row: ThresholdInterval(*row), old_rules))
        batch = db.ingest_batch('instrument-1', 'cape', 'mV', (ObservationInput(*row) for row in inputs))
        old_page = db.issue_rows('white-a', 'cape', batch.cutoff, 'A', 0, 24)
        old_day = db.close_day('shift-a', old_page.page_id)
        db.publish_schedule('B', 'cape', map(lambda row: ThresholdInterval(*row), new_rules))
        new_page = db.issue_rows('night-b', 'cape', batch.cutoff, 'B', 0, 24)
        new_day = db.close_day('shift-b', new_page.page_id)

    with Warehouse(path) as db:
        restored_page = db.get_review('white-a')
        restored_day = db.get_day('shift-a')
        reapplied_old = db.issue_rows('audit-a', 'cape', batch.cutoff, 'A', 0, 24)
        if restored_page != old_page or restored_day != old_day or reapplied_old.rows != restored_page.rows:
            raise AssertionError('fixed A evidence changed across reopening')
        if db.get_review('night-b') != new_page or db.get_day('shift-b') != new_day or db.get_head('cape') != 'B':
            raise AssertionError('the B publication or its fixed outcomes did not survive reopening')

    expected = {
        'A': [[1, 10, 'normal', 10, ['A', 0]], [2, 11, 'exceeded', 10, ['A', 0]],
              [3, 11, 'unruled', None, None], [4, None, 'missing', None, None]],
        'B': [[1, 10, 'unruled', None, None], [2, 11, 'normal', 12, ['B', 0]],
              [3, 11, 'unruled', None, None], [4, None, 'missing', None, None]],
    }
    actual = {'A': _page_rows(restored_page), 'B': _page_rows(new_page)}
    downstream_expected = {
        'A': {'normal': 1, 'exceeded': 1, 'unruled': 1, 'missing': 1},
        'B': {'normal': 1, 'exceeded': 0, 'unruled': 2, 'missing': 1},
    }
    categories = ('normal', 'exceeded', 'unruled', 'missing')
    downstream_actual = {
        revision: {category: getattr(day.totals, category) for category in categories}
        for revision, day in [('A', restored_day), ('B', new_day)]
    }
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError((expected, actual, downstream_expected, downstream_actual))
    scenario = {
        'case_id': 'v7.full_replacement',
        'input': {'station': 'cape', 'unit': 'mV', 'window': [0, 24], 'rows': inputs,
                  'rules': {'A': old_rules, 'B': new_rules}},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': ['observations/intake.py', 'rules/publish.py', 'rules/lookup.py',
                       'review/issue.py', 'review/archive.py', 'settlement/close_day.py'],
        'oracle': '手算四个小时是否属于相应半开区间，逐行比较读数和阈值，再按类别数行。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description='河岬监测数仓')
    subcommands = parser.add_subparsers(dest='command', required=True)
    initialize = subcommands.add_parser('init', help='初始化本地库并补齐样例站')
    initialize.add_argument('database', type=Path)
    subcommands.add_parser('demo', help='运行入仓、巡核、日结与重开剧本')
    args = parser.parse_args()
    if args.command == 'init':
        with Warehouse(args.database) as db:
            stations = db.bootstrap_stations()
        print(json.dumps([station.code for station in stations], ensure_ascii=False))
    else:
        with TemporaryDirectory(prefix='rivercape-demo-') as directory:
            _run_demo(Path(directory) / 'warehouse.sqlite')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
