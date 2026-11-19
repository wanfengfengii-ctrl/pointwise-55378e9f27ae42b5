from stations.bootstrap import DEMO_STATIONS

from tests import WarehouseTestCase


class IntakeTests(WarehouseTestCase):
    def test_bootstrap_preserves_station(self):
        initial = self.db.bootstrap_stations()
        field = self.db.register_station('dune', 'V', -3, 3)
        self.reopen()
        repeated = self.db.bootstrap_stations()
        self.assertEqual([station.code for station in initial], ['gull', 'reef'])
        self.assertEqual(repeated, initial)
        self.assertEqual(self.db.get_station('dune'), field)

    def test_bootstrap_station_identity(self):
        code = DEMO_STATIONS[0].code
        actual = self.db.register_station(code, 'V', -2, 3)
        for _ in range(2):
            stations = self.db.bootstrap_stations()
            self.assertEqual(stations[0], actual)
            self.assertEqual(self.db.get_station(code), actual)
        self.assertEqual((actual.unit, actual.reading_range.minimum, actual.reading_range.maximum), ('V', -2, 3))
        self.assertEqual(self.db.register_station(code, 'V', -2, 3), actual)
        with self.assertRaises(ValueError):
            self.db.register_station(code, 'mV', -2, 3)
        with self.assertRaises(ValueError):
            self.db.register_station('invalid-range', 'V', 4, 3)
        with self.assertRaises(KeyError):
            self.db.get_station('invalid-range')
        receipt = self.ingest('field', (1, 3), station=code, unit='V')
        self.assertEqual(receipt.observations[0].reading, 3)
        with self.assertRaises(ValueError):
            self.ingest('bad-sample', (1, 3), station=code, unit='mV')

    def test_wrong_unit(self):
        with self.assertRaisesRegex(ValueError, 'unit mismatch'):
            self.ingest('wrong-unit', (2, 10), station='cape', unit='V')
        self.assertEqual(self.db.latest_cutoff(), 0)
        self.assertEqual(self.db.list_observations('cape', 0, 0, 24), ())
        with self.assertRaises(KeyError):
            self.db.get_batch('wrong-unit')
        valid = self.ingest('right-unit', (2, 10))
        self.assertEqual(valid.cutoff, 1)
        self.assertEqual([row.source.batch_id for row in self.db.list_observations('cape', 1, 0, 24)], ['right-unit'])

    def test_range_atomic(self):
        accepted = self.ingest('edges', (0, -50), (1, 50), (2, None))
        self.assertEqual([row.reading for row in accepted.observations], [-50, 50, None])
        for bad_reading in (51, -51, 0.0, True):
            with self.subTest(bad_reading=bad_reading):
                with self.assertRaises(ValueError):
                    self.ingest('mixed', (1, 0), (2, bad_reading))
                with self.assertRaises(KeyError):
                    self.db.get_batch('mixed')
                self.assertEqual(self.db.latest_cutoff(), accepted.cutoff)
                self.assertEqual(self.db.list_observations('cape', accepted.cutoff, 0, 24), accepted.observations)
        valid = self.ingest('mixed', (1, 0), (2, -50))
        self.assertEqual(valid.cutoff, accepted.cutoff + 1)
        self.assertEqual([row.reading for row in self.db.list_observations('cape', valid.cutoff, 0, 24)],
                         [-50, 50, 0, None, -50])

    def test_duplicate_occurrences_and_retry(self):
        first = self.ingest('duplicates', (3, 11), (3, 11))
        retry = self.ingest('duplicates', (3, 11), (3, 11))
        self.assertEqual(retry, first)
        self.assertEqual(self.db.get_batch('duplicates'), first)
        self.assertEqual(first.cutoff, 1)
        self.assertEqual(self.db.latest_cutoff(), 1)
        rows = self.db.list_observations('cape', first.cutoff, 3, 4)
        self.assertEqual([(row.hour, row.reading, row.source.batch_id, row.source.position) for row in rows],
                         [(3, 11, 'duplicates', 0), (3, 11, 'duplicates', 1)])

    def test_changed_payload(self):
        first = self.ingest('raw', (4, 0), (4, None), (3, 10))
        for changed in (((4, None), (4, 0), (3, 10)), ((4, 0), (5, None), (3, 10))):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    self.ingest('raw', *changed)
        self.assertEqual(self.db.latest_cutoff(), first.cutoff)
        self.assertEqual(self.db.get_batch('raw'), first)
        rows = self.db.list_observations('cape', first.cutoff, 0, 24)
        self.assertEqual([(row.hour, row.reading, row.source.position) for row in rows],
                         [(3, 10, 2), (4, 0, 0), (4, None, 1)])
