import sqlite3

from tests import WarehouseTestCase


class ScheduleTests(WarehouseTestCase):
    def test_overlap_keeps_head(self):
        initial = self.publish('A', (0, 4, 10)).revision
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.publish('overlap', (0, 4, 10), (3, 8, 12))
        self.assertEqual(self.db.get_head('cape'), 'A')
        self.assertEqual(self.db.get_revision('cape', 'A'), initial)
        self.assertEqual(self.db.threshold_at('cape', 'A', 3).interval.threshold, 10)
        with self.assertRaises(KeyError):
            self.db.get_revision('cape', 'overlap')

    def test_adjacent_provenance(self):
        self.publish('adjacent', (3, 6, 12), (0, 3, 10))
        for hour, threshold, position in [(0, 10, 1), (2, 10, 1), (3, 12, 0), (5, 12, 0)]:
            with self.subTest(hour=hour):
                rule = self.db.threshold_at('cape', 'adjacent', hour)
                self.assertEqual((rule.interval.threshold, rule.source.publication_id, rule.source.position),
                                 (threshold, 'adjacent', position))
        self.assertIsNone(self.db.threshold_at('cape', 'adjacent', 6))

    def test_publish_atomic(self):
        original = self.publish('A', (0, 10, 10)).revision
        self.fault.arm()
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'not authorized'):
            self.publish('B', (2, 6, 12), (6, 8, 14))
        self.assertEqual(self.fault.denials, 1)
        self.reopen()
        self.assertEqual(self.db.get_head('cape'), 'A')
        self.assertEqual(self.db.get_revision('cape', 'A'), original)
        with self.assertRaises(KeyError):
            self.db.get_revision('cape', 'B')
        retry = self.publish('B', (2, 6, 12), (6, 8, 14))
        self.assertEqual(retry.current_head, 'B')
        self.assertEqual(self.db.get_head('cape'), 'B')
        self.assertEqual(self.db.get_revision('cape', 'B'), retry.revision)
        self.assertEqual(self.db.threshold_at('cape', 'B', 6).interval.threshold, 14)
        self.assertIsNone(self.db.threshold_at('cape', 'B', 0))

    def test_publication_retry(self):
        original = self.publish('A', (5, 9, 10), (0, 5, 10))
        self.assertEqual(original.current_head, 'A')
        next_publication = self.publish('B', (0, 9, 12))
        replay = self.publish('A', (5, 9, 10), (0, 5, 10))
        self.assertEqual(replay.revision, original.revision)
        self.assertEqual(replay.current_head, 'B')
        for rewrite in (((0, 5, 10), (5, 9, 10)), ((5, 9, 11), (0, 5, 10))):
            with self.subTest(rewrite=rewrite):
                with self.assertRaises(ValueError):
                    self.publish('A', *rewrite)
        self.assertEqual(self.db.get_head('cape'), 'B')
        self.assertEqual(self.db.get_revision('cape', 'B'), next_publication.revision)

    def test_invalid_first_publication_and_empty_replacement(self):
        for interval in [(0, 0, 1), (0, 1, -1), (0, True, 1), (0, 1, False)]:
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    self.publish('bad', interval)
                self.assertIsNone(self.db.get_head('cape'))
                with self.assertRaises(KeyError):
                    self.db.get_revision('cape', 'bad')
        with self.assertRaises(KeyError):
            self.publish('foreign', (0, 1, 10), station='unregistered')
        self.publish('A', (0, 1, 0))
        empty = self.publish('empty')
        self.assertEqual(empty.current_head, 'empty')
        self.assertEqual(empty.revision.rules, ())
        self.assertIsNone(self.db.threshold_at('cape', 'empty', 0))
        self.assertEqual(self.db.threshold_at('cape', 'A', 0).interval.threshold, 0)
