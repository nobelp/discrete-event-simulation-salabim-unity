import random
import unittest
from kx.coupled import run
from kx.wait_graph import diagnose


def stress_case(seed):
    rng=random.Random(seed)
    data=dict(format='kx-coupled',version=1,dataStatus='synthetic',durationSeconds=2000,seed=seed,
              liftsPerAisle=1+seed%2,workstationCapacity=2,infeedSeconds=.2,outfeedSeconds=.3,
              workstationSeconds=.5,shuttleCycleSeconds=.4,relocationSeconds=.1,pickupSeconds=.2,dropoffSeconds=.2,
              inBufferCapacity=1+seed%3,outBufferCapacity=1+seed%2,levelBufferCapacity=1+seed%2,
              lift=dict(speedMps=2,accelerationMps2=1,decelerationMps2=1,loadCapacity=2,
                        dispatchPolicy='same-level-fifo-batch',batchWaitSeconds=seed%3),
              levels=[dict(id=f'{a}-{l}',aisle=a,heightM=l*.5,storageCapacity=100,initialStock=20)
                      for a in ['A','B'] for l in [1,2,3]],jobs=[])
    if seed%2:
        data.update(returnToStorage=True,returnSeconds=.5,returnCapacity=2,returnLevel='B-3')
    for i in range(40):
        data['jobs'].append(dict(id=str(i),type='putaway' if i%2 else 'retrieve',
                                level=rng.choice(data['levels'])['id'],arrivalSeconds=rng.randrange(30),relocations=rng.randrange(4)))
    data['jobs'].sort(key=lambda j:j['arrivalSeconds'])
    return data


class WaitGraphTests(unittest.TestCase):
    def test_closed_two_resource_cycle(self):
        resources={k:dict(capacity=1,occupancy=1) for k in ['one','two']}
        actors=[dict(id='A',held=['one'],waitingFor='two'),dict(id='B',held=['two'],waitingFor='one')]
        result=diagnose(resources,actors)
        self.assertEqual(result['closedCircularWaitCount'],1)
        self.assertEqual(result['cycles'][0]['resources'],['one','two'])

    def test_a_cycle_with_an_active_outside_holder_is_not_closed(self):
        resources=dict(one=dict(capacity=2,occupancy=2),two=dict(capacity=1,occupancy=1))
        actors=[dict(id='A',held=['one'],waitingFor='two'),dict(id='B',held=['two'],waitingFor='one'),dict(id='active',held=['one'],waitingFor=None)]
        result=diagnose(resources,actors)
        self.assertEqual(result['circularWaitCount'],1)
        self.assertEqual(result['closedCircularWaitCount'],0)

    def test_not_full_resource_and_unknown_stock_wait_do_not_close_a_cycle(self):
        resources=dict(one=dict(capacity=2,occupancy=1),two=dict(capacity=1,occupancy=1))
        actors=[dict(id='A',held=['one'],waitingFor='two'),dict(id='B',held=['two'],waitingFor='one')]
        self.assertEqual(diagnose(resources,actors)['circularWaitCount'],0)
        actors[1]['waitingFor']='available-stock'
        self.assertEqual(diagnose(resources,actors)['circularWaitCount'],0)

    def test_long_wait_chain_is_not_a_cycle_or_recursion_error(self):
        resources={str(i):dict(capacity=1,occupancy=1) for i in range(1500)}
        actors=[dict(id=str(i),held=[str(i)],waitingFor=str(i+1) if i<1499 else None) for i in range(1500)]
        self.assertEqual(diagnose(resources,actors)['circularWaitCount'],0)

    def test_finite_workload_drains_without_return_loop(self):
        result=run(stress_case(0))
        self.assertEqual(result['completed'],40)
        self.assertEqual(result['waitDiagnostics']['closedCircularWaitCount'],0)
        self.assertTrue(all(m['occupancy']==0 for m in result['resources'].values()))

    def test_actual_reference_return_loop_cycle_is_identified(self):
        result=run(stress_case(1))
        self.assertLess(result['completed'],40)
        self.assertGreater(result['waitDiagnostics']['closedCircularWaitCount'],0)
        cycle=result['waitDiagnostics']['cycles'][0]
        self.assertIn('infeed',cycle['resources'])
        self.assertIn('return',cycle['resources'])
        self.assertTrue(any(p['type']=='lift-batch' for p in cycle['participants']))
        balance=result['balance']
        self.assertEqual(balance['initialStock']+balance['stored']+balance['returned']-balance['pickedForRetrieval'],balance['finalPhysicalStock'])

    def test_bidirectional_level_buffers_can_close_a_cycle_without_returns(self):
        data=stress_case(2)
        self.assertNotIn('returnToStorage',data)
        result=run(data)
        self.assertEqual(result['completed'],10)
        self.assertEqual(result['waitDiagnostics']['closedCircularWaitCount'],1)
        self.assertEqual(result['waitDiagnostics']['cycles'][0]['resources'],
                         ['level-in-B-2','level-out-B-2','lift-B','shuttle-B-2'])


if __name__=='__main__':unittest.main()
