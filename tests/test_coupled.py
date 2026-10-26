import unittest
from kx.coupled import run, travel


def case():
    return {"format":"kx-coupled","version":1,"dataStatus":"synthetic","durationSeconds":60,"seed":42,
            "infeedSeconds":1,"outfeedSeconds":1,"workstationSeconds":1,"shuttleCycleSeconds":2,"relocationSeconds":1,
            "pickupSeconds":1,"dropoffSeconds":1,"inBufferCapacity":1,"outBufferCapacity":1,"levelBufferCapacity":1,
            "lift":{"speedMps":1,"accelerationMps2":1,"decelerationMps2":1},
            "levels":[{"id":"L1","heightM":1,"storageCapacity":5,"initialStock":2}],"jobs":[]}


class CoupledChecks(unittest.TestCase):
    def test_single_putaway_independent_hand_schedule(self):
        d=case();d['jobs']=[{'id':'in','type':'putaway','level':'L1','arrivalSeconds':0,'relocations':0}]
        r=run(d)
        # Infeed 1 + lift pickup 1 + triangular lift travel 2 + drop 1 + shuttle pickup 1 + shuttle 2 = 8.
        self.assertEqual(r['jobs'][0]['completedAt'],8)
        self.assertEqual(r['inventory']['L1']['physical'],3)
        self.assertEqual(r['inventory']['L1']['available'],3)
        self.assertEqual(r['inventory']['L1']['reservedForPutaway'],0)

    def test_single_retrieve_independent_hand_schedule(self):
        d=case();d['jobs']=[{'id':'out','type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0}]
        r=run(d)
        # Shuttle 2 + drop 1 + lift empty approach 2 + pickup 1 + loaded 2 + drop 1 + outfeed 1 + workplace 1 = 11.
        self.assertEqual(r['jobs'][0]['completedAt'],11)
        self.assertEqual(r['inventory']['L1']['physical'],1)

    def test_mixed_flow_shared_lift_and_conservation(self):
        d=case();d['jobs']=[{'id':str(i),'type':'putaway' if i%2 else 'retrieve','level':'L1','arrivalSeconds':i,'relocations':0} for i in range(8)]
        r=run(d)
        self.assertEqual(r['arrived'],r['completed']+r['unfinished'])
        self.assertEqual(r['balance']['initialStock']+r['balance']['stored']-r['balance']['pickedForRetrieval'],r['balance']['finalPhysicalStock'])
        self.assertTrue(all(m['maximumOccupancy']<=m['capacity'] for m in r['resources'].values()))
        self.assertEqual(r['resources']['lift']['maximumOccupancy'],1)

    def test_outfeed_backpressure_reaches_lift_and_buffers(self):
        d=case();d['durationSeconds']=100;d['workstationSeconds']=80;d['levels'][0].update(storageCapacity=20,initialStock=15)
        d['jobs']=[{'id':str(i),'type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0} for i in range(12)]
        r=run(d)
        self.assertGreater(r['resources']['lift']['blockedSeconds'],0)
        self.assertGreater(r['unfinished'],0)
        self.assertLessEqual(r['resources']['out-buffer']['maximumOccupancy'],1)

    def test_no_phantom_stock_and_no_phantom_capacity(self):
        d=case();d['levels'][0]['initialStock']=0;d['jobs']=[{'id':'out','type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0}]
        r=run(d);self.assertEqual(r['completed'],0);self.assertEqual(r['jobs'][0]['stage'],'waiting:available-stock')
        d=case();d['levels'][0].update(storageCapacity=2,initialStock=2);d['jobs']=[{'id':'in','type':'putaway','level':'L1','arrivalSeconds':0,'relocations':0}]
        r=run(d);self.assertEqual(r['completed'],0);self.assertEqual(r['jobs'][0]['stage'],'waiting:storage-slot')

    def test_new_stock_can_supply_waiting_retrieval(self):
        d=case();d['levels'][0]['initialStock']=0;d['jobs']=[{'id':'out','type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0},{'id':'in','type':'putaway','level':'L1','arrivalSeconds':1,'relocations':0}]
        r=run(d);self.assertEqual(r['completed'],2);self.assertEqual(r['inventory']['L1']['physical'],0)

    def test_explicit_relocations_add_time_without_abc_assumption(self):
        a=case();a['jobs']=[{'id':'out','type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0}];b=case();b['jobs']=[{**a['jobs'][0],'relocations':3}]
        self.assertEqual(run(b)['jobs'][0]['completedAt']-run(a)['jobs'][0]['completedAt'],3)
        self.assertEqual(travel(1,1,1,1),2)

    def test_determinism_and_missing_input(self):
        d=case();self.assertEqual(run(d),run(d));del d['shuttleCycleSeconds']
        with self.assertRaises(ValueError):run(d)

class TopologyChecks(unittest.TestCase):
    def test_two_aisles_use_only_their_own_lifts(self):
        d=case();d['levels']=[{**d['levels'][0],'aisle':'G1'}, {'id':'L2','aisle':'G2','heightM':2,'storageCapacity':5,'initialStock':2}]
        d['liftsPerAisle']=2;d['jobs']=[{'id':str(i),'type':'retrieve','level':'L1' if i%2 else 'L2','arrivalSeconds':0,'relocations':0} for i in range(4)]
        r=run(d);self.assertEqual(r['topology']['totalLifts'],4);self.assertEqual(r['completed'],4)
        for j in r['jobs']:self.assertTrue(j['liftUnit'].startswith('G1' if j['level']=='L1' else 'G2'))
        self.assertTrue(all(m['maximumOccupancy']<=m['capacity'] for m in r['resources'].values()))

    def test_lift_specific_handover_times_do_not_change_shuttle_handover(self):
        for kind, expected in [('putaway',15),('retrieve',18)]:
            d=case();d['lift'].update(pickupSeconds=4,dropoffSeconds=5)
            d['jobs']=[{'id':'one','type':kind,'level':'L1','arrivalSeconds':0,'relocations':0}]
            self.assertEqual(run(d)['jobs'][0]['completedAt'],expected)
        d['lift']['pickupSeconds']=-1
        with self.assertRaises(ValueError):run(d)

    def test_nominal_component_limits_are_enforced_without_replacing_times(self):
        d=case();d['jobs']=[{'id':'out','type':'retrieve','level':'L1','arrivalSeconds':0,'relocations':0}]
        baseline=run(d)['jobs'][0]['completedAt'];d['shuttleRateBEhPerUnit']=120
        self.assertGreater(run(d)['jobs'][0]['completedAt'],baseline)
        d['lift']['rateBEhPerUnit']=60;d['durationSeconds']=120
        self.assertGreaterEqual(run(d)['jobs'][0]['completedAt'],92)

if __name__=='__main__': unittest.main()
