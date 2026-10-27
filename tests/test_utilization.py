import unittest
from test_coupled import case
from kx.coupled import run


class UtilizationChecks(unittest.TestCase):
    def test_hand_service_times_are_not_occupancy_or_capacity_percentages(self):
        d=case();d['jobs']=[dict(id='one',type='retrieve',level='L1',arrivalSeconds=0,relocations=0)]
        r=run(d)
        self.assertEqual(r['resources']['lift']['serviceSeconds'],6)
        self.assertEqual(r['resources']['shuttle-L1']['serviceSeconds'],3)
        self.assertEqual(r['resources']['outfeed']['serviceSeconds'],1)
        self.assertEqual(r['resources']['workstation']['serviceSeconds'],1)
        self.assertEqual(r['domains']['lifts']['serviceFraction'],6/60)
        self.assertEqual(r['domains']['conveyors']['serviceFraction'],1/120)
        self.assertEqual(r['workloadByLevel']['L1']['retrieve'],1)

    def test_blockage_is_separate_and_all_states_sum_to_one(self):
        d=case();d.update(durationSeconds=100,workstationSeconds=80)
        d['levels'][0].update(storageCapacity=20,initialStock=15)
        d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=0,relocations=0) for i in range(12)]
        r=run(d)
        self.assertGreater(r['domains']['lifts']['blockedFraction'],0)
        for m in r['resources'].values():
            self.assertAlmostEqual(sum(m[k] for k in ['serviceFraction','blockedFraction','rateWaitFraction','pausedFraction','otherHeldFraction','idleFraction']),1)
            self.assertLessEqual(m['serviceFraction'],m['occupiedFraction']+1e-9)

    def test_nominal_ceiling_wait_is_not_active_lift_work(self):
        d=case();d['lift']['rateBEhPerUnit']=60
        d['jobs']=[dict(id='one',type='retrieve',level='L1',arrivalSeconds=0,relocations=0)]
        r=run(d)
        self.assertEqual(r['resources']['lift']['serviceSeconds'],6)
        self.assertGreater(r['resources']['lift']['rateWaitSeconds'],0)

    def test_return_demand_and_shuttle_relocation_work_are_explicit(self):
        d=case();d.update(returnToStorage=True,returnSeconds=3,returnCapacity=1)
        d['jobs']=[dict(id='one',type='retrieve',level='L1',arrivalSeconds=0,relocations=3)]
        r=run(d)
        self.assertEqual(r['workloadByLevel']['L1']['plannedReturns'],1)
        self.assertEqual(r['workloadByLevel']['L1']['relocations'],{'3':1})
        self.assertEqual(r['resources']['shuttle-L1']['serviceSeconds'],9)
        self.assertEqual(r['resources']['lift']['visits'],2)


if __name__=='__main__':unittest.main()
