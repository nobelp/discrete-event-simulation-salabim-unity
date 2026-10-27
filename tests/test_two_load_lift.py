import unittest
from test_coupled import case
from kx.coupled import run


def dual():
    d=case()
    d.update(inBufferCapacity=2, levelBufferCapacity=2, outBufferCapacity=2)
    d['lift'].update(loadCapacity=2, dispatchPolicy='same-level-fifo-batch', batchWaitSeconds=3)
    return d


class TwoLoadLift(unittest.TestCase):
    def test_two_containers_share_one_physical_trip(self):
        d=dual();d['jobs']=[dict(id=str(i),type='putaway',level='L1',arrivalSeconds=0,relocations=0) for i in range(2)]
        r=run(d)
        self.assertEqual(r['putawayCompleted'],2)
        self.assertEqual(len(r['liftBatches']),1)
        self.assertEqual(r['liftBatches'][0]['loaded'],2)
        self.assertEqual(r['liftBatches'][0]['unloaded'],2)
        self.assertEqual(r['resources']['lift']['capacity'],1)
        self.assertEqual(r['resources']['lift']['maximumOccupancy'],1)
        # Two pickups + one triangular 1m loaded trip + two drops = 6s.
        self.assertEqual(r['resources']['lift']['serviceSeconds'],6)
        self.assertEqual(r['balance']['finalPhysicalStock'],4)

    def test_singleton_does_not_wait_forever_and_restarts_from_zero(self):
        d=dual();d['jobs']=[dict(id='one',type='retrieve',level='L1',arrivalSeconds=0,relocations=1)]
        r=run(d)
        self.assertEqual(r['retrievalCompleted'],1)
        self.assertEqual(r['liftBatches'][0]['loaded'],1)
        self.assertEqual(r,run(d))
        self.assertTrue(all(v==0 for v in r['trace'][0]['resources'].values()))

    def test_different_destination_levels_are_not_falsely_batched(self):
        d=dual();d['levels'].append(dict(id='L2',heightM=2,storageCapacity=5,initialStock=2))
        d['jobs']=[dict(id=k,type='putaway',level=k,arrivalSeconds=0,relocations=0) for k in ['L1','L2']]
        r=run(d)
        self.assertEqual(r['completed'],2)
        self.assertEqual([b['loaded'] for b in r['liftBatches']],[1,1])

    def test_blocked_drop_keeps_one_carrier_and_preserves_time_partition(self):
        d=dual();d.update(durationSeconds=100,workstationSeconds=80)
        d['levels'][0].update(storageCapacity=20,initialStock=15)
        d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=0,relocations=0) for i in range(12)]
        r=run(d)
        self.assertGreater(r['resources']['lift']['blockedSeconds'],0)
        for m in r['resources'].values():
            self.assertLessEqual(m['serviceFraction']+m['blockedFraction'],m['occupiedFraction']+1e-9)
            self.assertLessEqual(m['maximumOccupancy'],m['capacity'])
        self.assertEqual(r['balance']['initialStock']-r['balance']['pickedForRetrieval'],r['balance']['finalPhysicalStock'])

    def test_multiple_carriers_and_return_loop(self):
        d=dual();d.update(liftsPerAisle=2,returnToStorage=True,returnSeconds=1,returnCapacity=2,durationSeconds=120)
        d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=0,relocations=0) for i in range(2)]
        r=run(d)
        self.assertEqual(r['returnCompleted'],2)
        self.assertEqual(r['balance']['finalPhysicalStock'],2)
        self.assertLessEqual(r['resources']['lift']['maximumOccupancy'],2)
        self.assertTrue(all(b['loaded']<=2 for b in r['liftBatches']))

    def test_explicit_dispatch_rule_required(self):
        d=dual();del d['lift']['dispatchPolicy']
        with self.assertRaises(ValueError):run(d)
        d=dual();d['lift']['loadCapacity']=3
        with self.assertRaises(ValueError):run(d)

    def test_nominal_ceiling_counts_two_containers_and_keeps_handover_inside_budget(self):
        d=dual();d['lift']['rateBEhPerUnit']=60
        d['jobs']=[dict(id=str(i),type='putaway',level='L1',arrivalSeconds=0,relocations=0) for i in range(2)]
        r=run(d)
        self.assertEqual(r['putawayCompleted'],0)
        self.assertGreater(r['resources']['lift']['rateWaitSeconds'],0)
        d['durationSeconds']=140
        r=run(d)
        self.assertEqual(r['putawayCompleted'],2)
        self.assertEqual(r['liftBatches'][0]['completedAt']-r['liftBatches'][0]['dispatchAt'],120)

    def test_explicit_cross_aisle_return_uses_destination_carrier(self):
        d=dual();d['levels'][0]['aisle']='A'
        d['levels'].append(dict(id='B1',aisle='B',heightM=2,storageCapacity=5,initialStock=0))
        d.update(returnToStorage=True,returnSeconds=1,returnCapacity=2,returnLevel='B1',durationSeconds=100)
        d['jobs']=[dict(id='one',type='retrieve',level='L1',arrivalSeconds=0,relocations=0)]
        r=run(d)
        self.assertEqual(r['returnCompleted'],1)
        self.assertEqual(r['inventory']['B1']['physical'],1)
        self.assertTrue(r['jobs'][0]['returnLiftUnit'].startswith('B-'))


if __name__=='__main__':unittest.main()
