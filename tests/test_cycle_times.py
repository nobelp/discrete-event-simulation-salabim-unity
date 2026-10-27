import unittest
from kx.cycle_times import calculate, travel


def case():
    return dict(format='kx-analytical-cycles', version=1,
                motion=dict(speedMps=3, accelerationMps2=2, decelerationMps2=2),
                pickupSeconds=3, dropoffSeconds=3, singleAuxSeconds=2, doubleAuxSeconds=3,
                singlePoints=[dict(distanceM=20, probability=1)],
                doublePairs=[dict(putawayM=40/3, retrievalM=80/3, probability=1)])


class AnalyticalCycles(unittest.TestCase):
    def test_independent_hand_examples(self):
        result = calculate(case())
        self.assertAlmostEqual(result['single']['meanSeconds'], 24+1/3)
        self.assertAlmostEqual(result['double']['meanSeconds'], 37+5/18)
        self.assertAlmostEqual(result['double']['containerMovementsPerHour'], 2*result['double']['cyclesPerHour'])

    def test_triangular_boundary_and_asymmetric_motion(self):
        self.assertEqual(travel(0, 3, 2, 2), 0)
        self.assertAlmostEqual(travel(2, 3, 2, 2), 2)
        self.assertAlmostEqual(travel(4.5, 3, 2, 2), 3)
        self.assertAlmostEqual(travel(6, 2, 1, 2), 4.5)

    def test_weighted_times_before_rate(self):
        data=case()
        data['singlePoints']=[dict(distanceM=0, probability=.25), dict(distanceM=20, probability=.75)]
        result=calculate(data)['single']
        self.assertAlmostEqual(result['meanSeconds'], .25*8+.75*(24+1/3))
        self.assertAlmostEqual(result['cyclesPerHour'], 3600/result['meanSeconds'])

    def test_no_normalization_or_implicit_auxiliary_time(self):
        data=case(); data['singlePoints'][0]['probability']=1.02
        with self.assertRaises(ValueError): calculate(data)
        data=case(); del data['doubleAuxSeconds']
        with self.assertRaises(ValueError): calculate(data)
        with self.assertRaises(ValueError): travel(-1, 3, 2, 2)


if __name__ == '__main__': unittest.main()
