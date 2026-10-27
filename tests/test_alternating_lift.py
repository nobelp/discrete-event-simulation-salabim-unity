import unittest
from test_coupled import case
from kx.coupled import run


def alternating():
    d=case();d['lift'].update(loadCapacity=2,dispatchPolicy='alternating-in-out',initialDirection='putaway',batchWaitSeconds=0)
    return d


class AlternatingChecks(unittest.TestCase):
    def test_one_putaway_retrieve_pair_is_a_physical_round_trip(self):
        d=alternating();d['jobs']=[dict(id='in',type='putaway',level='L1',arrivalSeconds=0,relocations=0),dict(id='out',type='retrieve',level='L1',arrivalSeconds=0,relocations=0)]
        r=run(d)
        self.assertEqual(r['completed'],2)
        self.assertEqual([b['operation'] for b in r['liftBatches']],['putaway','retrieve'])
        self.assertEqual([b['loaded'] for b in r['liftBatches']],[1,1])
        self.assertEqual(r['resources']['lift']['serviceSeconds'],8)
        self.assertEqual(len(r['liftCycles']),1)
        self.assertEqual(r['liftCycles'][0]['completedAt']-r['liftCycles'][0]['startedAt'],8)

    def test_strict_alternation_never_silently_serves_two_same_direction(self):
        d=alternating();d['jobs']=[dict(id=str(i),type='putaway',level='L1',arrivalSeconds=0,relocations=0) for i in range(2)]
        r=run(d)
        self.assertEqual(r['putawayCompleted'],1)
        self.assertEqual(r['liftDispatchWaits'][0]['nextDirection'],'retrieve')
        self.assertEqual(r['liftDispatchWaits'][0]['queuedPutaway'],1)

    def test_closed_return_loop_alternates_for_each_physical_carrier(self):
        d=alternating();d['lift']['initialDirection']='retrieve'
        d.update(durationSeconds=200,liftsPerAisle=2,returnToStorage=True,returnSeconds=1,returnCapacity=2,inBufferCapacity=2,outBufferCapacity=2)
        d['levels'][0].update(storageCapacity=20,initialStock=10)
        # Two initial requests use both carriers; later arrivals leave time for
        # the deliberately small buffers to drain. Dense blocking has its own tests.
        d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=0 if i<2 else i*30,relocations=0) for i in range(6)]
        r=run(d)
        self.assertEqual(r['returnCompleted'],6)
        self.assertEqual(r['inventory']['L1']['physical'],10)
        self.assertEqual({b['liftUnit'] for b in r['liftBatches']},{'A1-H1','A1-H2'})
        for unit in ['A1-H1','A1-H2']:
            steps=[b['operation'] for b in r['liftBatches'] if b['liftUnit']==unit]
            self.assertTrue(all(step==('retrieve' if i%2==0 else 'putaway') for i,step in enumerate(steps)))

    def test_five_named_workplaces_have_individual_counts_without_double_domain_capacity(self):
        d=case();d.update(durationSeconds=300,workstationCapacity=5)
        d['levels'][0].update(storageCapacity=30,initialStock=20)
        d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=i,relocations=0,workstation=i%5+1) for i in range(10)]
        r=run(d)
        self.assertEqual([r['workplaces'][str(i)]['completed'] for i in range(1,6)],[2]*5)
        self.assertEqual(r['domains']['workplaces']['capacity'],5)
        self.assertTrue(all(r['resources']['workplace-'+str(i)]['maximumOccupancy']<=1 for i in range(1,6)))
        del d['jobs'][0]['workstation']
        with self.assertRaises(ValueError):run(d)


if __name__=='__main__':unittest.main()
