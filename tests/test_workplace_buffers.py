import unittest
from test_coupled import case
from kx.coupled import run


def buffered_case():
    d=case();d.update(durationSeconds=90,workstationCapacity=2,workstationSeconds=40,workstationBufferCapacity=3)
    d['levels'][0].update(storageCapacity=20,initialStock=10)
    d['jobs']=[dict(id=str(i),type='retrieve',level='L1',arrivalSeconds=0,relocations=0,workstation=target) for i,target in enumerate([1,1,1,1,1,2])]
    return d


class WorkplaceBufferChecks(unittest.TestCase):
    def test_three_waiting_places_are_separate_from_processing(self):
        r=run(buffered_case())
        self.assertEqual(r['resources']['workplace-buffer-1']['capacity'],3)
        self.assertEqual(r['resources']['workplace-buffer-1']['maximumOccupancy'],3)
        self.assertEqual(r['resources']['workplace-1']['maximumOccupancy'],1)
        self.assertEqual(r['domains']['workplaces']['capacity'],2)
        self.assertTrue(all(m['maximumOccupancy']<=m['capacity'] for m in r['resources'].values()))
        self.assertTrue(all(n==0 for n in r['trace'][0]['resources'].values()))

    def test_buffer_releases_common_outfeed_before_service_starts(self):
        d=buffered_case();d['jobs']=d['jobs'][:2]+[d['jobs'][-1]]
        buffered=run(d);del d['workstationBufferCapacity'];direct=run(d)
        by_id=lambda result:{j['id']:j for j in result['jobs']}
        a,b=by_id(buffered),by_id(direct)
        self.assertLess(a['1']['workplaceBufferArrivedAt'],a['1']['workplaceStartedAt'])
        self.assertLess(a['5']['workplaceStartedAt'],b['5']['workplaceStartedAt'])
        self.assertGreater(direct['resources']['outfeed']['blockedSeconds'],buffered['resources']['outfeed']['blockedSeconds'])

    def test_full_buffer_backpressures_common_outfeed(self):
        d=buffered_case();d['workstationBufferCapacity']=1
        r=run(d)
        self.assertGreater(r['resources']['outfeed']['blockedSeconds'],0)
        self.assertEqual(r['arrived'],r['completed']+r['unfinished'])

    def test_target_and_positive_capacity_required(self):
        for capacity in [0,-1,True,1.5]:
            d=buffered_case();d['workstationBufferCapacity']=capacity
            with self.assertRaises(ValueError):run(d)
        d=buffered_case();del d['jobs'][0]['workstation']
        with self.assertRaises(ValueError):run(d)

    def test_no_parameter_keeps_direct_handover(self):
        d=buffered_case();del d['workstationBufferCapacity']
        r=run(d)
        self.assertFalse(any(k.startswith('workplace-buffer-') for k in r['resources']))


if __name__=='__main__':unittest.main()
