"""Independent event-area and censored-order checks."""
import unittest
from test_coupled import case
from kx.coupled import run


class BacklogChecks(unittest.TestCase):
    def test_single_completion_hand_area(self):
        d = case(); d['jobs'] = [dict(id='out', type='retrieve', level='L1', arrivalSeconds=0, relocations=0)]
        r = run(d)
        self.assertEqual(r['flowSeconds']['p99'], 11)
        self.assertEqual(r['flowSeconds']['count'], 1)
        self.assertEqual(r['backlog']['maximum'], 1)
        self.assertEqual(r['backlog']['timeWeightedMean'], 11/60)
        self.assertEqual(r['backlog']['atEnd'], 0)
        self.assertIsNone(r['pendingAgeSeconds']['max'])

    def test_incomplete_ages_not_mixed_into_completed_percentiles(self):
        d = case(); d['levels'][0]['initialStock'] = 0
        d['jobs'] = [dict(id=str(i), type='retrieve', level='L1', arrivalSeconds=i*10, relocations=0) for i in range(2)]
        r = run(d)
        self.assertEqual(r['backlog']['timeWeightedMean'], 110/60)
        self.assertEqual(r['backlog']['atEnd'], 2)
        self.assertEqual(r['pendingAgeSeconds']['mean'], 55)
        self.assertEqual(r['pendingAgeSeconds']['p99'], 60)
        self.assertIsNone(r['flowSeconds']['p99'])

    def test_same_time_events_aggregated_and_empty_case_defined(self):
        d = case(); d['levels'][0]['initialStock'] = 1
        d['jobs'] = [dict(id=str(i), type='retrieve', level='L1', arrivalSeconds=i*11, relocations=0) for i in range(2)]
        r = run(d)
        self.assertEqual(r['backlog']['maximum'], 1)
        self.assertEqual(r['backlog']['timeWeightedMean'], 1)
        r = run(case())
        self.assertEqual(r['backlog']['maximum'], 0)
        self.assertIsNone(r['flowSeconds']['p99'])

    def test_backlog_is_exact_even_when_animation_trace_truncated(self):
        d = case(); d['levels'][0]['initialStock'] = 0
        d['jobs'] = [dict(id=str(i), type='retrieve', level='L1', arrivalSeconds=0, relocations=0) for i in range(2600)]
        r = run(d)
        self.assertTrue(r['traceTruncated'])
        self.assertEqual(r['backlog']['atEnd'], 2600)
        self.assertEqual(r['backlog']['timeWeightedMean'], 2600)

    def test_return_cycle_boundary_is_storage_not_workplace(self):
        d = case(); d.update(returnToStorage=True, returnSeconds=3, returnCapacity=1)
        d['jobs'] = [dict(id='out', type='retrieve', level='L1', arrivalSeconds=0, relocations=0)]
        r = run(d)
        self.assertEqual(r['backlog']['timeWeightedMean'], 22/60)
        self.assertEqual(r['flowSeconds']['p99'], 22)
        self.assertEqual(r['backlog']['completionBoundary'], 'return-stored')


if __name__ == '__main__': unittest.main()
