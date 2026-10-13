import tempfile
import unittest
from pathlib import Path
from alarms import AlarmStore,CATALOG
from simulator import Plant,load_config
from simulation_controls import SimulationControls
from sunspec import native_registers,native_map,combine,EVENTS

class SunSpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg=load_config();self.cfg['mode']='demo';self.cfg['weather']['enabled']=False;self.cfg['simulation_control_file']=str(Path(self.tmp.name)/'control.json')
        self.cfg['faulted_units']=[]
        self.p=Plant(self.cfg,persist=False)
        self.c=SimulationControls(self.cfg['simulation_control_file'],True)
    def test_native_model_and_measurements(self):
        words=native_registers(self.p.devices[2],2)
        self.assertEqual(words[:4],[0x5375,0x6e53,1,66])
        self.assertEqual(words[70:72],[103,50]);self.assertEqual(words[-2:],[65535,0])
        self.assertEqual(len(words),124)
        fields={p['key']:words[p['pdu_address']-40000:p['pdu_address']-40000+p['register_count']] for p in native_map() if p['model']==103}
        sf=fields['W_SF'][0];sf=sf-65536 if sf>=32768 else sf
        self.assertAlmostEqual(fields['W'][0]*10**sf/1000,self.p.devices[2]['power_kw'],delta=.01)
        self.assertEqual(fields['St'],[4]);self.assertEqual(fields['Evt1'],[0,0]);self.assertEqual(fields['Evt2'],[0,0])
    def test_multiple_events_and_clear_restart(self):
        total=self.p.total[1]
        self.c.change(2,1,True,'Tester');self.c.change(2,10,True,'Tester');self.p.step(1)
        d=self.p.devices[2]
        self.assertEqual(d['alarm_code'],1026);self.assertEqual(d['status'],7);self.assertEqual(d['power_kw'],0)
        self.assertEqual(d['dc_current'],0);self.assertEqual(d['v_l1n'],260);self.assertEqual(d['dc_voltage'],1100)
        self.p.step(5);stopped_total=self.p.total[1];self.p.step(5);self.assertEqual(self.p.total[1],stopped_total)
        self.c.change(2,1,False,'Tester');self.p.step(1);self.assertEqual(self.p.devices[2]['alarm_code'],1024)
        self.c.change(2,None,False,'Tester');self.p.step(1);self.assertEqual(self.p.devices[2]['status'],3)
        self.p.step(5);self.assertEqual(self.p.devices[2]['status'],4);self.assertGreater(self.p.devices[2]['power_kw'],0)
        self.assertGreaterEqual(self.p.total[1],total)
    def test_warning_derate_and_manual_stop(self):
        self.c.change(1,5,True,'Tester');self.p.step(1)
        self.assertGreater(self.p.devices[1]['power_kw'],0);self.assertEqual(self.p.devices[1]['status'],4)
        self.c.change(1,12,True,'Tester');self.p.step(1);d=self.p.devices[1]
        self.assertEqual(d['status'],5);self.assertAlmostEqual(d['dc_power_kw']*d['efficiency']/100,d['power_kw'])
        self.c.change(1,6,True,'Tester');self.p.step(1);self.assertEqual(self.p.devices[1]['status'],1);self.assertEqual(self.p.devices[1]['power_kw'],0)
    def test_thermal_clear_requires_cooling(self):
        self.c.change(3,7,True,'Tester');self.p.step(1)
        self.c.change(3,7,False,'Tester');self.p.step(1)
        self.assertEqual(self.p.devices[3]['status'],7);self.assertTrue(self.p.devices[3]['alarm_code']&128)
        self.p.step(180);self.assertLess(self.p.devices[3]['temperature'],75);self.assertEqual(self.p.devices[3]['status'],4)
    def test_history_independent_dedup_ack_restart(self):
        path=Path(self.tmp.name)/'history.sqlite3';s=AlarmStore(path)
        rows=[r for r in CATALOG if r['unit_id']==2 and r['bit'] in (1,10)]
        for r in rows:s.receive(r['ioa'],True,'2026-10-13T11:00:00+00:00')
        for r in rows:s.receive(r['ioa'],True,'2026-10-13T11:00:01+00:00')
        self.assertEqual(len(s.history()),2);s.acknowledge(s.history()[0]['id'],'Tester')
        s.receive(rows[0]['ioa'],False,'2026-10-13T11:00:02+00:00');s.close();s=AlarmStore(path)
        self.assertEqual(len(s.open_rows()),1);self.assertEqual(len(s.history()),2);s.close()
    def test_bitfield_precision_and_analyzer_aggregate(self):
        self.assertEqual(combine(65535,65535),4294967295)
        self.assertIsNone(combine(1.5,0));self.assertIsNone(combine(0,None))
        self.c.change(1,0,True,'Tester');self.c.change(2,10,True,'Tester');self.p.step(1)
        self.assertEqual(self.p.devices[11]['alarm_code'],1025)
        self.assertAlmostEqual(self.p.devices[11]['power_kw'],sum(self.p.devices[u]['power_kw'] for u in range(1,11)))
        self.assertEqual(len(EVENTS),16);self.assertEqual(len(CATALOG),160)

if __name__=='__main__':unittest.main(verbosity=2)
