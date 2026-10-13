"""Isolated lab integration: real Modbus -> TEST c104 gateway -> receiver/API.
Does not touch your RTU, live ports, state or alarm history. Not a Telediagram substitute.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parent

def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def run():
    processes=[]
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'solar_lab'
        shutil.copytree(ROOT,root,ignore=shutil.ignore_patterns('.venv','__pycache__','*.sqlite3*','state.json','simulation_control*.json'))
        cfg=json.loads((root/'config.json').read_text());cfg.update(modbus_host='127.0.0.1',iec_host='127.0.0.1',web_host='127.0.0.1',modbus_port=freeport(),iec_port=freeport(),web_port=freeport(),stale_seconds=3,faulted_units=[])
        cfg['mode']='demo';cfg['weather']['enabled']=False
        (root/'config.json').write_text(json.dumps(cfg))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base=f"http://127.0.0.1:{cfg['web_port']}"
        def fetch(path='/api/state'):return json.load(opener.open(base+path,timeout=2))
        def post(path,body):
            req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
            return json.load(opener.open(req,timeout=2))
        def wait(fn,timeout=25):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                try:
                    data=fetch();value=fn(data)
                    if value:return data
                except OSError:pass
                time.sleep(.15)
            raise AssertionError('Beklenen zincir durumu oluşmadı')
        def inv(d,u=2):return next(x for x in d['devices'] if x['unit_id']==u)['signals']
        log=(root/'test.log').open('w')
        try:
            for script in ['simulator.py','test_gateway.py','receiver.py']:
                processes.append(subprocess.Popen([sys.executable,'-u',str(root/script)],cwd=root,stdout=log,stderr=log))
            data=wait(lambda d:d['connected'] and all(s['value'] is not None for dev in d['devices'] for s in dev['signals'].values()))
            assert abs(data['devices'][10]['signals']['power_kw']['value']-sum(x['signals']['power_kw']['value'] for x in data['devices'][:10]))<1
            assert len([s for dev in data['devices'] for s in dev['signals']])==302
            print('PASS: 302 measurements over real Modbus / IEC104; aggregate verified')
            for bit in (1,10):assert post('/api/simulation/2/event',dict(bit=bit,active=True,operator='Integration test'))['status']=='REQUESTED'
            data=wait(lambda d:inv(d)['alarm_code']['value']==1026 and inv(d)['status']['value']==7 and inv(d)['power_kw']['value']==0)
            active=[a for a in data['alarms'] if a['unit_id']==2 and a['active']]
            assert {a['bit'] for a in active}=={1,10}
            hist=fetch('/api/alarms/history')['items'];assert len(hist)==2
            post(f"/api/alarms/{hist[0]['id']}/ack",dict(operator='Integration test'))
            assert len(fetch('/api/alarms/history')['items'])==2
            print('PASS: manual test -> simulator -> Modbus -> IEC104 -> two independent persisted alarms; acknowledgement')
            post('/api/simulation/2/event',dict(bit=1,active=False,operator='Integration test'))
            wait(lambda d:inv(d)['alarm_code']['value']==1024)
            post('/api/simulation/2/clear',dict(operator='Integration test'))
            wait(lambda d:inv(d)['alarm_code']['value']==0 and inv(d)['status']['value']==4 and inv(d)['power_kw']['value']>0)
            assert all(a['cleared_at'] for a in fetch('/api/alarms/history')['items'])
            print('PASS: individual clear, remaining fault, restart and alarm normalisation')
            post('/api/simulation/2/event',dict(bit=5,active=True,operator='Integration test'))
            wait(lambda d:inv(d)['alarm_code']['value']==32 and inv(d)['power_kw']['value']>0)
            processes[0].terminate();processes[0].wait(timeout=8)
            data=wait(lambda d:inv(d)['power_kw']['quality']=='BAD')
            alarm=next(a for a in data['alarms'] if a['unit_id']==2 and a['bit']==5)
            assert alarm['active'] is None and alarm['last_known_active']
            processes[1].terminate();processes[1].wait(timeout=8)
            data=wait(lambda d:not d['connected'])
            assert all(s['value'] is None for dev in data['devices'] for s in dev['signals'].values())
            assert any(a['cleared_at'] is None for a in fetch('/api/alarms/history')['items'])
            print('PASS: bad Modbus quality and IEC104 disconnect preserve last alarm; no false clear')
        finally:
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()
                    try:p.wait(timeout=8)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
            log.close()
            txt=(root/'test.log').read_text()
            if 'Traceback' in txt:print(txt)

if __name__=='__main__':run()
