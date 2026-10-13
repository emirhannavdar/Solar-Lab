import asyncio
from datetime import datetime, timedelta
import json
import math
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from simulator import Plant, load_config, serve_client
from signals import SIGNALS, mappings
from test_gateway import read_bank

ROOT=Path(__file__).resolve().parent

class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.cfg=load_config();self.cfg['mode']='demo';self.cfg['weather']['enabled']=False;self.p=Plant(self.cfg,persist=False)
    def test_consistency(self):
        self.p.step(3600)
        for u in range(1,11):
            d=self.p.devices[u]
            self.assertLessEqual(d['power_kw'],self.p.rated)
            self.assertAlmostEqual(d['dc_power_kw']*d['efficiency']/100,d['power_kw'])
            self.assertAlmostEqual(d['dc_voltage']*d['dc_current']/1000,d['dc_power_kw'])
            self.assertAlmostEqual(math.hypot(d['power_kw'],d['reactive_kvar']),d['apparent_kva'])
            self.assertAlmostEqual(sum(d[f'v_l{i}n']*d[f'i_l{i}'] for i in (1,2,3))*d['power_factor']/1000,d['power_kw'])
            self.assertGreater(d['daily_kwh'],0)
        for key in ('power_kw','daily_kwh','total_kwh','reactive_kvar','i_l1'):
            self.assertAlmostEqual(self.p.devices[11][key],sum(self.p.devices[u][key] for u in range(1,11)))
    def test_integration(self):
        before=self.p.total[0];daily_before=self.p.daily[0];p0=self.p.devices[1]['power_kw'];self.p.step(1)
        expected=(p0+self.p.devices[1]['power_kw'])/2/3600
        self.assertAlmostEqual(self.p.daily[0]-daily_before,expected,places=10)
        self.assertAlmostEqual(self.p.total[0]-before,expected,places=9)
    def test_night_midnight_fault(self):
        self.cfg['demo_start']='2026-06-21T23:59:59+03:00'
        p=Plant(self.cfg,persist=False);p.daily=[10.0]*10;p.step(2)
        self.assertEqual(p.daily,[0]*10);self.assertEqual(p.devices[11]['power_kw'],0)
        self.cfg['demo_start']='2026-06-21T12:00:00+03:00';self.cfg['faulted_units']=[4]
        p=Plant(self.cfg,persist=False)
        self.assertEqual(p.devices[4]['power_kw'],0);self.assertEqual(p.devices[4]['status'],7)
        self.assertGreater(p.devices[3]['power_kw'],0)
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.cfg['state_file']=str(Path(tmp)/'state.json')
            p=Plant(self.cfg);p.step(40);p.save();other=Plant(self.cfg)
            self.assertEqual(other.daily,p.daily);self.assertEqual(other.total,p.total);self.assertEqual(other.now,p.now)
    def test_map_and_float_order(self):
        rows=list(mappings());self.assertEqual(len(rows),302)
        self.assertEqual(len({x['ioa'] for x in rows}),302)
        for u in range(1,12):
            words=self.p.registers(u)
            self.assertEqual(len(words),56)
            decoded=struct.unpack('>28f',struct.pack('>56H',*words))
            for index,(key,_,_) in enumerate(SIGNALS):
                self.assertAlmostEqual(decoded[index],self.p.devices[u].get(key,0),delta=max(.001,abs(decoded[index])*1e-6))

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_fc03_fc04_and_exceptions(self):
        cfg=load_config();cfg['mode']='demo';cfg['weather']['enabled']=False;p=Plant(cfg,persist=False)
        server=await asyncio.start_server(lambda r,w:serve_client(r,w,p),'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        async with server:
            r,w=await asyncio.open_connection('127.0.0.1',port)
            for fc,unit,start,count,error in [(3,1,0,56,None),(4,11,0,56,None),(3,1,40000,124,None),(4,2,40108,6,None),(3,11,40000,2,2),(3,12,0,2,11),(3,1,55,2,2),(3,1,0,0,3),(6,1,0,1,1)]:
                request=struct.pack('>HHHBBHH',9,0,6,unit,fc,start,count)
                w.write(request[:3]);await w.drain();w.write(request[3:]);await w.drain()
                tid,proto,length,uid=struct.unpack('>HHHB',await r.readexactly(7))
                body=await r.readexactly(length-1)
                self.assertEqual((tid,proto,uid),(9,0,unit))
                if error:self.assertEqual(body,bytes([fc|128,error]))
                else:
                    self.assertEqual(len(body),2+count*2);self.assertEqual(body[:2],bytes([fc,count*2]))
                    if start==40000:self.assertEqual(body[2:6],b'SunS')
            w.close();await w.wait_closed()

if __name__=='__main__': unittest.main(verbosity=2)
