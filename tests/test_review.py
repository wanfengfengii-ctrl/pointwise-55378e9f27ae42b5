from tests import WarehouseTestCase


class ReviewTests(WarehouseTestCase):
    def test_edges_missing_and_unruled(self):
        self.publish('A', (1, 3, 10))
        batch = self.ingest('raw', (1, 10), (2, 11), (3, 11), (4, None))
        page = self.db.issue_rows('page-a', 'cape', batch.cutoff, 'A', 0, 24)
        self.assertEqual([row.classification.value for row in page.rows],
                         ['normal', 'exceeded', 'unruled', 'missing'])
        self.assertEqual([row.threshold for row in page.rows], [10, 10, None, None])
        self.assertEqual([(row.rule_source.publication_id, row.rule_source.position) for row in page.rows[:2]],
                         [('A', 0), ('A', 0)])
        self.assertEqual([row.rule_source for row in page.rows[2:]], [None, None])
        self.assertEqual(self.db.get_review('page-a'), page)

    def test_foreign_schedule(self):
        self.db.register_station('reef', 'mV', -50, 50)
        self.publish('local', (0, 5, 10))
        self.publish('foreign', (0, 5, 12), station='reef')
        batch = self.ingest('raw', (1, 11))
        with self.assertRaisesRegex(ValueError, 'belongs to station'):
            self.db.issue_rows('page', 'cape', batch.cutoff, 'foreign', 0, 24)
        with self.assertRaises(KeyError):
            self.db.get_review('page')
        page = self.db.issue_rows('page', 'cape', batch.cutoff, 'local', 0, 24)
        self.assertEqual(page.rows[0].classification.value, 'exceeded')
        self.assertEqual(page.rows[0].rule_source.publication_id, 'local')

    def test_fixed_cutoff(self):
        self.db.register_station('reef', 'mV', -50, 50)
        self.publish('A', (1, 4, 10))
        self.ingest('local-first', (3, 11), (2, 10), (2, 10), (1, 11), (4, 20))
        self.ingest('other-station', (2, 11), station='reef')
        through = self.ingest('local-second', (2, 11), (3, 10))
        self.ingest('late', (2, 13))
        page = self.db.issue_rows('fixed', 'cape', through.cutoff, 'A', 2, 4)
        self.assertEqual(page.binding.cutoff, 3)
        actual = [
            (row.observation.hour, row.observation.reading, row.observation.source.batch_id,
             row.observation.source.cutoff, row.observation.source.position, row.classification.value)
            for row in page.rows
        ]
        self.assertEqual(actual, [
            (2, 10, 'local-first', 1, 1, 'normal'), (2, 10, 'local-first', 1, 2, 'normal'),
            (2, 11, 'local-second', 3, 0, 'exceeded'), (3, 11, 'local-first', 1, 0, 'exceeded'),
            (3, 10, 'local-second', 3, 1, 'normal'),
        ])
        self.reopen()
        self.assertEqual(self.db.get_review('fixed'), page)

    def test_missing_with_rule(self):
        self.publish('A', (0, 2, 0))
        batch = self.ingest('raw', (0, 0), (1, None), (2, None))
        page = self.db.issue_rows('missing', 'cape', batch.cutoff, 'A', 0, 3)
        self.assertEqual([row.classification.value for row in page.rows], ['normal', 'missing', 'missing'])
        self.assertEqual([row.threshold for row in page.rows], [0, None, None])
        self.assertEqual(page.rows[0].rule_source.position, 0)
        self.assertIsNone(page.rows[1].rule_source)
        self.assertIsNone(page.rows[2].rule_source)

    def test_page_identity(self):
        self.publish('A', (0, 1, 0))
        self.publish('B', (0, 1, 1))
        self.ingest('raw', (0, 0))
        original = self.db.issue_rows('empty', 'cape', 0, 'A', 0, 24)
        self.assertEqual(original.rows, ())
        self.assertEqual(self.db.issue_rows('empty', 'cape', 0, 'A', 0, 24), original)
        for cutoff, revision, start, end in [(1, 'A', 0, 24), (0, 'B', 0, 24), (0, 'A', 1, 24)]:
            with self.subTest(cutoff=cutoff, revision=revision, start=start):
                with self.assertRaises(ValueError):
                    self.db.issue_rows('empty', 'cape', cutoff, revision, start, end)
        self.assertEqual(self.db.get_review('empty'), original)
        with self.assertRaises(KeyError):
            self.db.get_review('new')
        with self.assertRaises(ValueError):
            self.db.issue_rows('new', 'cape', 0, 'A', 1, 1)
        for cutoff in (-1, True, 2):
            with self.subTest(cutoff=cutoff):
                with self.assertRaises(ValueError):
                    self.db.issue_rows('new', 'cape', cutoff, 'A', 0, 24)
        with self.assertRaises(KeyError):
            self.db.get_review('new')
        page = self.db.issue_rows('new', 'cape', 1, 'A', 0, 24)
        self.assertEqual(page.rows[0].classification.value, 'normal')

    def test_unknown_revision(self):
        with self.assertRaises(KeyError):
            self.db.issue_rows('pending', 'cape', 0, 'absent', 0, 24)
        with self.assertRaises(KeyError):
            self.db.get_review('pending')
        self.publish('A', (0, 1, 1))
        page = self.db.issue_rows('pending', 'cape', 0, 'A', 0, 24)
        self.assertEqual(page.binding.revision, 'A')

    def test_exact_signed_hours_and_readings_after_reopen(self):
        large = 1 << 80
        self.db.register_station('wide', 'mV', -large, large + 1)
        self.publish('wide-a', (-large, -1, large), (-1, 1, 0), station='wide')
        batch = self.ingest('raw-wide', (0, 0), (-large, large), (-2, large + 1), (-1, -large),
                            station='wide')
        self.reopen()
        page = self.db.issue_rows('wide-page', 'wide', batch.cutoff, 'wide-a', -large, 1)
        self.assertEqual([(row.observation.hour, row.observation.reading, row.classification.value,
                           row.threshold, row.rule_source.position) for row in page.rows], [
            (-large, large, 'normal', large, 0), (-2, large + 1, 'exceeded', large, 0),
            (-1, -large, 'normal', 0, 1), (0, 0, 'normal', 0, 1),
        ])
        self.reopen()
        self.assertEqual(self.db.get_review('wide-page'), page)
