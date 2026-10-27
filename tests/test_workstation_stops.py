"""Explicit deterministic interruption schedules; no assumed failure rates."""
import unittest
from test_coupled import case
from kx.coupled import run


class WorkstationStopChecks(unittest.TestCase):
    def scenario(self):
        d = case()
        d['jobs'] = [dict(id='out', type='retrieve', level='L1', arrivalSeconds=0, relocations=0)]
        return d

    def test_stop_at_processing_start(self):
        d = self.scenario(); d['workstationStops'] = [[10, 20]]
        r = run(d)
        self.assertEqual(r['jobs'][0]['retrievedAt'], 21)
        self.assertEqual(r['resources']['workstation']['processingSeconds'], 1)
        self.assertEqual(r['resources']['workstation']['pausedOccupiedSeconds'], 10)
        self.assertEqual(r['resources']['workstation']['scheduledDowntimeSeconds'], 10)

    def test_partial_service_resumes_across_multiple_stops(self):
        d = self.scenario(); d['workstationStops'] = [[10.25, 11.25], [11.5, 12.5]]
        r = run(d)
        self.assertEqual(r['jobs'][0]['retrievedAt'], 13)
        self.assertEqual(r['resources']['workstation']['processingSeconds'], 1)
        self.assertEqual(r['resources']['workstation']['pausedOccupiedSeconds'], 2)

    def test_idle_stop_does_not_delay_later_work(self):
        d = self.scenario(); d['workstationStops'] = [[1, 5]]
        r = run(d)
        self.assertEqual(r['jobs'][0]['retrievedAt'], 11)
        self.assertEqual(r['resources']['workstation']['pausedOccupiedSeconds'], 0)

    def test_measurement_end_clips_downtime_and_preserves_open_stock(self):
        d = self.scenario(); d.update(durationSeconds=15, workstationStops=[[10, 100]])
        r = run(d)
        self.assertEqual(r['retrievalCompleted'], 0)
        self.assertEqual(r['jobs'][0]['stage'], 'workstation-stopped')
        self.assertEqual(r['resources']['workstation']['pausedOccupiedSeconds'], 5)
        self.assertEqual(r['resources']['workstation']['scheduledDowntimeSeconds'], 5)
        self.assertEqual(r['balance']['finalPhysicalStock'], 1)

    def test_downstream_pause_propagates_and_return_stays_balanced(self):
        d = self.scenario(); d.update(durationSeconds=100, workstationStops=[[0, 80]], returnToStorage=True, returnSeconds=3, returnCapacity=1)
        d['levels'][0].update(storageCapacity=20, initialStock=15)
        d['jobs'] = [{**d['jobs'][0], 'id':str(i)} for i in range(12)]
        r = run(d)
        self.assertGreater(r['resources']['lift']['blockedSeconds'], 0)
        self.assertTrue(all(m['maximumOccupancy'] <= m['capacity'] for m in r['resources'].values()))
        self.assertEqual(r['balance']['initialStock'] + r['balance']['stored'] + r['balance']['returned'] - r['balance']['pickedForRetrieval'], r['balance']['finalPhysicalStock'])

    def test_invalid_and_overlapping_intervals_rejected(self):
        for stops in [[[5, 5]], [[-1, 5]], [[5, 10], [9, 11]], [[60, 70]], [[2]], 'random']:
            d = self.scenario(); d['workstationStops'] = stops
            with self.assertRaises(ValueError): run(d)


if __name__ == '__main__': unittest.main()
