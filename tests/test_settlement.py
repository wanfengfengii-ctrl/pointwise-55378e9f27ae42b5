import sqlite3

from tests import WarehouseTestCase


def totals_of(day):
    return (day.totals.normal, day.totals.exceeded, day.totals.unruled, day.totals.missing)


class SettlementTests(WarehouseTestCase):
    def test_close_then_reopen_after_schedule_change(self):
        self.publish('A', (1, 3, 10))
        batch = self.ingest('instrument-1', (1, 10), (2, 11), (3, 11), (4, None))
        page_a = self.db.issue_rows('white-a', 'cape', batch.cutoff, 'A', 0, 24)
        day_a = self.db.close_day('shift-a', 'white-a')
        self.assertEqual(totals_of(day_a), (1, 1, 1, 1))
        self.assertEqual((day_a.station, day_a.day, day_a.page_id, day_a.totals.row_count), ('cape', 0, 'white-a', 4))
        self.publish('B', (2, 3, 12))
        page_b = self.db.issue_rows('night-b', 'cape', batch.cutoff, 'B', 0, 24)
        self.assertEqual([row.classification.value for row in page_b.rows], ['unruled', 'normal', 'unruled', 'missing'])
        self.assertEqual([row.threshold for row in page_b.rows], [None, 12, None, None])
        self.assertEqual((page_b.rows[1].rule_source.publication_id, page_b.rows[1].rule_source.position), ('B', 0))
        day_b = self.db.close_day('shift-b', 'night-b')
        self.assertEqual(totals_of(day_b), (1, 0, 2, 1))
        self.reopen()
        self.assertEqual(self.db.get_head('cape'), 'B')
        self.assertEqual(self.db.get_review('white-a'), page_a)
        self.assertEqual(self.db.get_day('shift-a'), day_a)
        self.assertEqual(self.db.get_review('night-b'), page_b)
        self.assertEqual(self.db.get_day('shift-b'), day_b)
        another_a = self.db.issue_rows('audit-a', 'cape', batch.cutoff, 'A', 0, 24)
        self.assertEqual(another_a.binding, page_a.binding)
        self.assertEqual(another_a.rows, page_a.rows)
        self.assertEqual([row.classification.value for row in another_a.rows], ['normal', 'exceeded', 'unruled', 'missing'])
        self.assertEqual([row.rule_source.publication_id for row in another_a.rows[:2]], ['A', 'A'])
        next_b = self.db.issue_rows('audit-b', 'cape', batch.cutoff, 'B', 0, 24)
        self.assertEqual(next_b.rows, page_b.rows)

    def test_day_alignment(self):
        self.publish('A', (0, 48, 10))
        batch = self.ingest('boundary', (0, 11), (1, None), (23, 10), (24, 9))
        for page_id, start, end in [('shifted', 1, 25), ('short', 0, 23)]:
            with self.subTest(window=(start, end)):
                page = self.db.issue_rows(page_id, 'cape', batch.cutoff, 'A', start, end)
                if page_id == 'shifted':
                    self.assertEqual([row.observation.hour for row in page.rows], [1, 23, 24])
                with self.assertRaisesRegex(ValueError, 'aligned 24-hour'):
                    self.db.close_day('day', page_id)
                with self.assertRaises(KeyError):
                    self.db.get_day('day')
        page = self.db.issue_rows('aligned', 'cape', batch.cutoff, 'A', 0, 24)
        self.assertEqual([row.observation.hour for row in page.rows], [0, 1, 23])
        close = self.db.close_day('day', 'aligned')
        self.assertEqual(close.page_id, 'aligned')
        self.assertEqual(totals_of(close), (1, 1, 0, 1))

    def test_close_identity(self):
        self.publish('A', (0, 48, 10))
        self.db.issue_rows('first', 'cape', 0, 'A', 0, 24)
        self.db.issue_rows('second', 'cape', 0, 'A', 24, 48)
        with self.assertRaises(KeyError):
            self.db.get_day('close')
        with self.assertRaises(KeyError):
            self.db.close_day('close', 'unknown-page')
        original = self.db.close_day('close', 'first')
        self.assertEqual(self.db.close_day('close', 'first'), original)
        with self.assertRaises(ValueError):
            self.db.close_day('close', 'second')
        self.assertEqual(self.db.get_day('close'), original)
        self.assertEqual(original.page_id, 'first')

    def test_empty_day(self):
        self.publish('A', (0, 48, 10))
        batch = self.ingest('before-day', (23, 11), (48, 11))
        page = self.db.issue_rows('empty-next', 'cape', batch.cutoff, 'A', 24, 48)
        self.assertEqual(page.rows, ())
        close = self.db.close_day('zero', page.page_id)
        self.assertEqual(close.day, 1)
        self.assertEqual(totals_of(close), (0, 0, 0, 0))
        self.assertEqual(close.totals.row_count, 0)
        self.reopen()
        self.assertEqual(self.db.get_day('zero'), close)

    def test_commit_failure_and_retry(self):
        self.publish('A', (1, 3, 10))
        batch = self.ingest('raw', (1, 10), (2, 11), (3, 11), (4, None))
        page = self.db.issue_rows('source', 'cape', batch.cutoff, 'A', 0, 24)
        self.fault.arm()
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'not authorized'):
            self.db.close_day('retry', page.page_id)
        self.assertEqual(self.fault.denials, 1)
        with self.assertRaises(KeyError):
            self.db.get_day('retry')
        self.assertEqual(self.db.get_review('source'), page)
        self.reopen()
        self.assertEqual(self.db.get_review('source'), page)
        with self.assertRaises(KeyError):
            self.db.get_day('retry')
        retry = self.db.close_day('retry', 'source')
        self.assertEqual(retry.page_id, 'source')
        self.assertEqual(totals_of(retry), (1, 1, 1, 1))
        self.assertEqual(self.db.close_day('retry', 'source'), retry)
        self.reopen()
        self.assertEqual(self.db.get_day('retry'), retry)
