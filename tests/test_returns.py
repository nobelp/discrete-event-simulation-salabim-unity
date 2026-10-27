"""Synthetic closed-loop cases, independent of any supplier data."""
import unittest
from test_coupled import case
from kx.coupled import run


class ReturnChecks(unittest.TestCase):
    def scenario(self):
        d = case()
        d.update(returnToStorage=True, returnSeconds=3, returnCapacity=1)
        d['jobs'] = [dict(id='out', type='retrieve', level='L1', arrivalSeconds=0, relocations=0)]
        return d

    def test_hand_schedule_and_reuse_of_real_resources(self):
        r = run(self.scenario())
        # Retrieval reaches workplace at 11; return transfer 3; putaway path 8.
        self.assertEqual(r['jobs'][0]['retrievedAt'], 11)
        self.assertEqual(r['jobs'][0]['returnedAt'], 22)
        self.assertEqual(r['jobs'][0]['completedAt'], 22)
        self.assertEqual(r['retrievalCompleted'], 1)
        self.assertEqual(r['returnCompleted'], 1)
        self.assertEqual(r['putawayCompleted'], 0)
        self.assertEqual(r['balance']['finalPhysicalStock'], 2)
        self.assertEqual(r['inventory']['L1']['reservedForPutaway'], 0)
        self.assertGreater(r['resources']['infeed']['area'], 0)

    def test_open_return_is_not_a_completed_cycle_or_lost_inventory(self):
        d = self.scenario(); d['durationSeconds'] = 12
        r = run(d)
        self.assertEqual((r['retrievalCompleted'], r['returnCompleted'], r['unfinished']), (1, 0, 1))
        self.assertEqual(r['returnsPending'], 1)
        self.assertEqual(r['balance']['finalPhysicalStock'], 1)

    def test_return_supplies_a_waiting_retrieval(self):
        d = self.scenario(); d['levels'][0]['initialStock'] = 1
        d['jobs'] += [{**d['jobs'][0], 'id': 'next'}]
        r = run(d)
        self.assertEqual(r['returnCompleted'], 2)
        self.assertEqual(r['inventory']['L1']['physical'], 1)
        # Lift remains at the level after return: next retrieval saves 2 s approach.
        self.assertEqual(r['jobs'][1]['retrievedAt'], 31)

    def test_finite_return_zone_backpressure_reaches_workstation(self):
        d = self.scenario(); d['returnSeconds'] = 100; d['durationSeconds'] = 80
        d['jobs'] += [{**d['jobs'][0], 'id': 'next'}, dict(id='new', type='putaway', level='L1', arrivalSeconds=0, relocations=0)]
        r = run(d)
        self.assertGreater(r['resources']['workstation']['blockedSeconds'], 0)
        self.assertTrue(all(m['maximumOccupancy'] <= m['capacity'] for m in r['resources'].values()))
        self.assertEqual(r['arrived'], r['completed'] + r['unfinished'])
        self.assertEqual(r['balance']['initialStock'] + r['balance']['stored'] + r['balance']['returned'] - r['balance']['pickedForRetrieval'], r['balance']['finalPhysicalStock'])

    def test_return_slot_wait_is_counted_and_no_slot_is_invented(self):
        d = self.scenario(); d['levels'][0].update(storageCapacity=1, initialStock=1)
        d['returnSeconds'] = 30
        d['jobs'] += [dict(id='new', type='putaway', level='L1', arrivalSeconds=4, relocations=0)]
        r = run(d)
        self.assertEqual(r['returnCompleted'], 0)
        self.assertEqual(r['jobs'][0]['stage'], 'waiting:storage-slot')
        self.assertGreater(r['resources']['return']['blockedSeconds'], 0)
        self.assertEqual(r['inventory']['L1']['physical'], 1)

    def test_missing_return_parameters_are_rejected(self):
        for field in ['returnSeconds', 'returnCapacity']:
            d = self.scenario(); del d[field]
            with self.assertRaises(ValueError): run(d)
        d = self.scenario(); d['returnToStorage'] = 'yes'
        with self.assertRaises(ValueError): run(d)


if __name__ == '__main__': unittest.main()
