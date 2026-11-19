import sqlite3

from tests import WarehouseTestCase


def coverage_map(page):
    values = {}
    for start, end, threshold, source in page.coverage:
        value = None if source is None else (threshold, source.publication_id, source.position)
        for hour in range(start, end):
            values[hour] = value
    return values


def source_of(rule):
    return (rule.interval.threshold, rule.source.publication_id, rule.source.position)


class IssueReviewTests(WarehouseTestCase):
    def test_fixes_current_cutoff_and_full_coverage(self):
        self.publish('A', (0, 10, 10))
        batch = self.ingest('raw', (1, 11), (3, 11), (4, 11), (8, 11))
        page = self.db.issue_review('a', 'cape', 'A', 0, 10)
        self.assertEqual(page.binding.cutoff, batch.cutoff)
        self.assertEqual(page.binding.revision, 'A')
        self.assertEqual([row.observation.hour for row in page.rows], [1, 3, 4, 8])
        self.assertEqual(page.coverage, ((0, 10, 10, page.coverage[0].source),))
        self.assertEqual(coverage_map(page), dict.fromkeys(range(10), (10, 'A', 0)))
        self.assertEqual(self.db.get_review('a'), page)
        self.ingest('late', (5, 11))
        self.assertEqual(self.db.issue_review('a', 'cape', 'A', 0, 10), page)
        self.assertEqual(page.binding.cutoff, 1)

    def test_gap_coverage_and_historical_revision(self):
        self.publish('A', (2, 4, 5))
        self.publish('B', (0, 2, 7))
        page = self.db.issue_review('old', 'cape', 'A', 0, 6)
        self.assertEqual(page.binding.revision, 'A')
        self.assertEqual([(start, end, threshold) for start, end, threshold, _ in page.coverage],
                         [(0, 2, None), (2, 4, 5), (4, 6, None)])
        self.assertEqual([None if source is None else source.publication_id
                          for _, _, _, source in page.coverage], [None, 'A', None])
        self.assertEqual(self.db.get_head('cape'), 'B')

    def test_entry_and_parameter_occupancy(self):
        self.publish('A', (0, 10, 10))
        self.db.issue_rows('plain', 'cape', 0, 'A', 0, 10)
        with self.assertRaises(ValueError):
            self.db.issue_review('plain', 'cape', 'A', 0, 10)
        page = self.db.issue_review('cred', 'cape', 'A', 0, 10)
        with self.assertRaises(ValueError):
            self.db.issue_rows('cred', 'cape', 0, 'A', 0, 10)
        for revision, start, end in (('A', 1, 10), ('A', 0, 9)):
            with self.subTest(revision=revision, start=start):
                with self.assertRaises(ValueError):
                    self.db.issue_review('cred', 'cape', revision, start, end)
        with self.assertRaises(KeyError):
            self.db.issue_review('missing', 'cape', 'absent', 0, 10)
        with self.assertRaises(KeyError):
            self.db.get_review('missing')
        self.assertEqual(self.db.get_review('cred'), page)


class AmendmentTests(WarehouseTestCase):
    def seed(self):
        self.publish('A', (0, 10, 10))
        self.ingest('raw', (1, 11), (3, 11), (4, 11), (8, 11))
        return self.db.issue_review('a', 'cape', 'A', 0, 10)

    def assert_conflict(self, request_id, page_id, edits, hour):
        head = self.db.get_head('cape')
        with self.assertRaises(ValueError) as caught:
            self.db.amend_review(request_id, page_id, edits)
        self.assertEqual(caught.exception.conflict_hour, hour)
        self.assertEqual(self.db.get_head('cape'), head)
        with self.assertRaises(KeyError):
            self.db.get_revision('cape', request_id)

    def test_same_value_reissue_conflict_at_sample_free_hour(self):
        page = self.seed()
        self.db.amend_review('W', 'a', [(5, 6, 10)])
        self.assert_conflict('stale', 'a', [(2, 8, 12)], 5)
        self.assertEqual(self.db.threshold_at('cape', 'A', 5).interval.threshold, 10)

    def test_amendments_keep_provenance_and_replay(self):
        page = self.seed()
        receipt_w = self.db.amend_review('W', 'a', [(5, 6, 10)])
        self.assertEqual(receipt_w.current_head, 'W')
        w = self.db.get_revision('cape', 'W')
        self.assertEqual([source_of(rule) for rule in w.rules],
                         [(10, 'A', 0), (10, 'W', 0), (10, 'A', 0)])
        w_page = self.db.issue_review('w', 'cape', 'W', 0, 12)
        expected_w = dict.fromkeys(range(10), (10, 'A', 0))
        expected_w.update({5: (10, 'W', 0), 10: None, 11: None})
        self.assertEqual(coverage_map(w_page), expected_w)
        receipt_b = self.db.amend_review('B', 'w', [(2, 8, 12), (10, 11, 7)])
        self.assert_conflict('gap-stale', 'w', [(10, 11, 9)], 10)
        self.assertEqual(receipt_b.revision.publication_id, 'B')
        b_page = self.db.issue_review('b', 'cape', 'B', 0, 10)
        expected_b = dict.fromkeys(range(10), (10, 'A', 0))
        expected_b.update(dict.fromkeys(range(2, 8), (12, 'B', 0)))
        self.assertEqual(coverage_map(b_page), expected_b)
        self.db.amend_review('C', 'b', [(4, 5, None)])
        expected_c = dict.fromkeys(range(10), (10, 'A', 0))
        expected_c.update(dict.fromkeys(range(2, 8), (12, 'B', 0)))
        expected_c.update({4: None, 10: (7, 'B', 1), 11: None})
        c = self.db.get_revision('cape', 'C')
        actual_c = {}
        for hour in expected_c:
            rule = self.db.threshold_at('cape', 'C', hour)
            actual_c[hour] = None if rule is None else source_of(rule)
        self.assertEqual(actual_c, expected_c)
        self.assertIsNone(self.db.threshold_at('cape', 'C', 4))
        self.assertEqual([source_of(rule) for rule in c.rules],
                         [(10, 'A', 0), (12, 'B', 0), (12, 'B', 0), (10, 'A', 0), (7, 'B', 1)])
        self.reopen()
        self.assertEqual(self.db.get_review('w'), w_page)
        self.assertEqual(self.db.get_review('b'), b_page)
        self.assertEqual(self.db.get_revision('cape', 'C'), c)
        self.assertEqual(self.db.amend_review('B', 'w', [(2, 8, 12), (10, 11, 7)]), receipt_b)
        self.assertEqual(self.db.get_head('cape'), 'C')
        with self.assertRaises(ValueError):
            self.db.amend_review('B', 'w', [(2, 8, 13)])

    def test_whole_replacement_invalidates_by_source_not_only_value(self):
        page = self.seed()
        self.db.amend_review('D', 'a', [(8, 9, 11)])
        self.assertEqual(self.db.threshold_at('cape', 'D', 8).source.publication_id, 'D')
        self.publish('R', (0, 12, 10))
        self.assert_conflict('whole-stale', 'a', [(2, 8, 12)], 2)
        self.assertEqual(self.db.threshold_at('cape', 'R', 4).source.publication_id, 'R')

    def test_edit_validation_and_unknown_pages(self):
        self.seed()
        self.db.issue_rows('plain', 'cape', 0, 'A', 0, 10)
        for edits in ([], [(0, 0, 1)], [(0, 1, -1)], [(0, 1, True)], [(True, 2, 1)],
                      [(0, 1, 1), (0, 2, 3)], [(-1, 1, 1)], [(9, 11, 1)],
                      [(0, 1, 1.0)], [(0, 1)], [None], 5):
            with self.subTest(edits=edits):
                with self.assertRaises(ValueError):
                    self.db.amend_review('bad', 'a', edits)
                self.assertEqual(self.db.get_head('cape'), 'A')
                with self.assertRaises(KeyError):
                    self.db.get_revision('cape', 'bad')
        with self.assertRaises(KeyError):
            self.db.amend_review('bad', 'unknown-page', [(0, 1, 1)])
        with self.assertRaises(ValueError):
            self.db.amend_review('bad', 'plain', [(0, 1, 1)])
        with self.assertRaises(ValueError):
            self.db.amend_review(' ', 'a', [(0, 1, 1)])
        adjacent = self.db.amend_review('adjacent', 'a', [(0, 2, 10), (2, 4, 12)])
        self.assertEqual([source_of(rule) for rule in adjacent.revision.rules],
                         [(10, 'adjacent', 0), (12, 'adjacent', 1), (10, 'A', 0)])
        self.db.issue_review('adjacent-page', 'cape', 'adjacent', 0, 10)
        unordered = self.db.amend_review('unordered', 'adjacent-page',
                                         [(6, 8, 13), (0, 2, 10)])
        self.assertEqual([source_of(rule) for rule in unordered.revision.rules],
                         [(10, 'unordered', 1), (12, 'adjacent', 1),
                          (10, 'A', 0), (13, 'unordered', 0), (10, 'A', 0)])

    def test_edit_input_position_is_not_sorted_position(self):
        page = self.seed()
        receipt = self.db.amend_review('positions', 'a', [(6, 8, 13), (0, 2, 11)])
        self.assertEqual([source_of(rule) for rule in receipt.revision.rules],
                         [(11, 'positions', 1), (10, 'A', 0),
                          (13, 'positions', 0), (10, 'A', 0)])
        self.assertEqual(self.db.threshold_at('cape', 'positions', 6).source.position, 0)
        self.assertEqual(self.db.threshold_at('cape', 'positions', 1).source.position, 1)
        with self.assertRaises(ValueError):
            self.db.amend_review('positions', 'a', [(0, 2, 11), (6, 8, 13)])
        self.assertEqual(self.db.get_review('a'), page)

    def test_request_space_shared_with_publications(self):
        page = self.seed()
        receipt = self.db.amend_review('W', 'a', [(5, 6, 10)])
        with self.assertRaises(ValueError):
            self.publish('W', (0, 4, 1))
        self.publish('X', (0, 4, 1))
        with self.assertRaises(ValueError):
            self.db.amend_review('X', 'a', [(0, 1, 2)])
        replay = self.db.amend_review('W', 'a', [(5, 6, 10)])
        self.assertEqual(replay, receipt)
        self.assertEqual(replay.current_head, 'W')
        self.assertEqual(self.db.get_head('cape'), 'X')

    def test_commit_failure_rolls_back_and_retry(self):
        self.seed()
        self.fault.arm()
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'not authorized'):
            self.db.amend_review('W', 'a', [(5, 6, 10)])
        self.assertEqual(self.fault.denials, 1)
        self.assertEqual(self.db.get_head('cape'), 'A')
        with self.assertRaises(KeyError):
            self.db.get_revision('cape', 'W')
        retry = self.db.amend_review('W', 'a', [(5, 6, 10)])
        self.assertEqual(retry.current_head, 'W')
        self.assertEqual(self.db.get_head('cape'), 'W')

    def test_no_rule_agreement_and_window_trim(self):
        self.publish('gap', (0, 2, 10), (8, 10, 10))
        self.ingest('raw', (5, 11))
        page = self.db.issue_review('gap-page', 'cape', 'gap', 0, 10)
        self.assertEqual([(start, end, threshold) for start, end, threshold, _ in page.coverage],
                         [(0, 2, 10), (2, 8, None), (8, 10, 10)])
        receipt = self.db.amend_review('gap-fill', 'gap-page', [(2, 8, 5)])
        self.assertEqual([source_of(rule) for rule in receipt.revision.rules],
                         [(10, 'gap', 0), (5, 'gap-fill', 0), (10, 'gap', 1)])
        narrow = self.db.issue_review('narrow', 'cape', 'gap-fill', 3, 6)
        self.assertEqual([(start, end, threshold) for start, end, threshold, _ in narrow.coverage],
                         [(3, 6, 5)])
        with self.assertRaises(ValueError):
            self.db.amend_review('trim', 'narrow', [(2, 4, 5)])
        stale = self.db.issue_review('stale-window', 'cape', 'gap', 3, 4)
        self.assertEqual([(start, end, threshold) for start, end, threshold, _ in stale.coverage],
                         [(3, 4, None)])
        with self.assertRaises(ValueError) as caught:
            self.db.amend_review('stale-edit', 'stale-window', [(3, 4, 5)])
        self.assertEqual(caught.exception.conflict_hour, 3)
        current = self.db.issue_review('current-window', 'cape', 'gap-fill', 3, 4)
        self.assertEqual([(start, end, threshold) for start, end, threshold, _ in current.coverage],
                         [(3, 4, 5)])
        filling = self.db.amend_review('fill-window', 'current-window', [(3, 4, 8)])
        self.assertEqual(filling.current_head, 'fill-window')
        self.assertEqual(source_of(self.db.threshold_at('cape', 'fill-window', 3)),
                         (8, 'fill-window', 0))

    def test_credential_day_close_and_reopen(self):
        self.publish('A', (0, 24, 10))
        self.ingest('raw', (0, 11), (1, 10), (2, None))
        page = self.db.issue_review('day', 'cape', 'A', 0, 24)
        self.db.amend_review('clear', 'day', [(1, 2, None)])
        close = self.db.close_day('shift', 'day')
        self.assertEqual((close.totals.normal, close.totals.exceeded,
                          close.totals.unruled, close.totals.missing), (1, 1, 0, 1))
        self.reopen()
        self.assertEqual(self.db.get_review('day'), page)
        self.assertEqual(self.db.get_day('shift'), close)
        self.assertEqual(self.db.get_head('cape'), 'clear')
