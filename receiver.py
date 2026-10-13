"""IEC104-only backend. No Modbus or simulator imports / fallback."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time
import c104
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from alarms import CATALOG, BY_IOA, AlarmStore
from sunspec import combine, STATES, EVENTS, EVENT_BY_BIT
from simulation_controls import SimulationControls
from weather_service import WeatherService
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from signals import mappings

ROOT=Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
MAP=list(mappings())
ALARM_STORE=AlarmStore(ROOT / CFG.get('alarm_db_file','device_alarms.sqlite3'))
CONTROLS=SimulationControls(ROOT / CFG.get('simulation_control_file','simulation_control_v2.json'),CFG.get('simulation_actions_enabled',False))
WEATHER=WeatherService(CFG,ROOT)
LOCK=threading.Lock()
CACHE={}
EVENT_CACHE={}
HISTORY=deque(maxlen=1800)
CLIENT=None
CONNECTION=None
POINTS=[]

def on_receive(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    value=float(point.value)
    quality=point.quality
    good=math.isfinite(value) and (quality is None or quality.is_good())
    offset=point.io_address%1000
    if offset in (19,20,26,27,28):
        good=good and value==int(value) and (int(value) in STATES if offset==19 else 0<=value<=65535)
    with LOCK:
        CACHE[point.io_address]=dict(value=value if math.isfinite(value) else None,
            good=good,quality=str(quality),received_at=datetime.now(timezone.utc).isoformat(),
            source_time=point.recorded_at.isoformat() if point.recorded_at else None,
            monotonic=time.monotonic())
        unit=point.io_address//1000
        if unit in range(1,11) and offset in (20,26):
            lo=CACHE.get(unit*1000+20);hi=CACHE.get(unit*1000+26)
            now=time.monotonic()
            valid=lo and hi and lo['good'] and hi['good'] and all(now-x['monotonic']<=CFG['stale_seconds'] for x in (lo,hi))
            mask=combine(lo['value'],hi['value']) if valid else None
            if mask is not None:
                received=datetime.now(timezone.utc).isoformat()
                for row in CATALOG:
                    if row['unit_id']!=unit:continue
                    active=bool(mask & row['mask'])
                    EVENT_CACHE[row['ioa']]=dict(value=int(active),good=True,received_at=received,monotonic=now,source_time=None)
                    ALARM_STORE.receive(row['ioa'],active,received)
    return c104.ResponseState.SUCCESS

async def poll():
    last_gi=0
    while True:
        if CONNECTION.is_connected and time.monotonic()-last_gi>10:
            CONNECTION.interrogation(common_address=CFG['common_address'],wait_for_response=False)
            last_gi=time.monotonic()
        with LOCK:
            item=CACHE.get(11001)
            if item and item['good'] and CONNECTION.is_connected and time.monotonic()-item['monotonic'] < CFG['stale_seconds']:
                if not HISTORY or HISTORY[-1]['received_at']!=item['received_at']:
                    HISTORY.append(dict(received_at=item['received_at'],power_kw=item['value']))
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app):
    global CLIENT, CONNECTION, POINTS
    CLIENT=c104.Client(tick_rate_ms=100,command_timeout_ms=5000)
    CONNECTION=CLIENT.add_connection(ip=CFG['iec_host'],port=CFG['iec_port'],init=c104.Init.INTERROGATION)
    station=CONNECTION.add_station(common_address=CFG['common_address'])
    iec_type=getattr(c104.Type,CFG['iec_type'])
    if CFG['iec_type'] not in ('M_ME_NC_1','M_ME_TF_1'):
        raise ValueError('iec_type M_ME_NC_1 (13) veya M_ME_TF_1 (36) olmalı')
    POINTS=[]
    for row in MAP:
        point=station.add_point(io_address=row['ioa'],type=iec_type)
        point.on_receive(callable=on_receive)
        POINTS.append(point)
    CLIENT.start()
    task=asyncio.create_task(poll())
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        CLIENT.stop()

app=FastAPI(title='Solar Lab — IEC104 receiver',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/state')
def state():
    now=time.monotonic()
    connected=bool(CONNECTION and CONNECTION.is_connected)
    devices=[]
    with LOCK:
        for unit in range(1,12):
            signals={}
            for row in MAP:
                if row['unit_id']!=unit: continue
                item=CACHE.get(row['ioa'])
                age=now-item['monotonic'] if item else None
                valid=bool(connected and item and item['good'] and age<=CFG['stale_seconds'])
                signals[row['key']]=dict(value=item['value'] if valid else None,
                    last_value=item['value'] if item else None,
                    quality='GOOD' if valid else ('MISSING' if not item else ('BAD' if not item['good'] else 'STALE')),
                    age_seconds=round(age,1) if age is not None else None,
                    received_at=item['received_at'] if item else None,
                    source_time=item['source_time'] if item else None,
                    label=row['label'],unit=row['unit'],ioa=row['ioa'])
            devices.append(dict(unit_id=unit,name='Analizör' if unit==11 else f'İnvertör {unit:02}',signals=signals))
        history=list(HISTORY)
    return dict(source='IEC104',connected=connected,endpoint=f"{CFG['iec_host']}:{CFG['iec_port']}",
        common_address=CFG['common_address'],devices=devices,history=history,
        alarms=alarm_snapshot(),simulation=CONTROLS.snapshot(),sunspec=dict(states=STATES,events=EVENTS),weather=WEATHER.snapshot())

def alarm_snapshot():
    now=time.monotonic()
    connected=bool(CONNECTION and CONNECTION.is_connected)
    opened=ALARM_STORE.open_rows()
    result=[]
    with LOCK:
        for row in CATALOG:
            item=EVENT_CACHE.get(row['ioa'])
            age=now-item['monotonic'] if item else None
            source_items=[CACHE.get(row['unit_id']*1000+n) for n in (20,26)]
            source_valid=all(s and s['good'] and now-s['monotonic']<=CFG['stale_seconds'] for s in source_items)
            valid=bool(connected and source_valid and item and item['good'] and age<=CFG['stale_seconds'])
            active=bool(item['value']) if valid else None
            occurrence=opened.get(row['ioa'])
            result.append(dict(**row,active=active,quality='GOOD' if valid else ('BAD' if any(s and not s['good'] for s in source_items) else 'MISSING' if any(s is None for s in source_items) else 'STALE'),
                age_seconds=round(age,1) if age is not None else None,
                received_at=item['received_at'] if item else None,
                state=('ACTIVE_ACKNOWLEDGED' if occurrence and occurrence['acknowledged_at'] else 'ACTIVE_UNACKNOWLEDGED') if active else ('NORMAL' if active is False else 'UNKNOWN'),
                occurrence=occurrence,last_known_active=occurrence is not None))
    return result

class AckRequest(BaseModel):
    operator: str = Field(min_length=1,max_length=80)

@app.get('/api/alarms/catalog')
def alarm_catalog(): return CATALOG

@app.get('/api/weather')
@app.get('/weather')
def weather_current():
    data=WEATHER.snapshot()
    return dict(success=data['usable'],latitude=WEATHER.profile['latitude'],longitude=WEATHER.profile['longitude'],data=data)

@app.get('/weather/hourly')
def weather_hourly():
    status=WEATHER.snapshot()
    return dict(success=status['usable'],status=status['status'],data=WEATHER.read().get('hourly') if status['usable'] else None)

@app.get('/weather/day')
def weather_daily():
    status=WEATHER.snapshot()
    return dict(success=status['usable'],status=status['status'],data=WEATHER.read().get('daily') if status['usable'] else None)

@app.get('/weather/panel')
def weather_panel():return dict(success=True,data=dict(panel=CFG.get('panel'),location=WEATHER.options.get('location'),**WEATHER.profile))

@app.get('/api/alarms/history')
def alarm_history(limit:int=200,before:int|None=None):
    if not 1<=limit<=1000: raise HTTPException(400,'limit 1–1000 olmalı')
    rows=ALARM_STORE.history(limit,before)
    return dict(items=rows,next_before=rows[-1]['id'] if len(rows)==limit else None)

@app.get('/api/alarms/events')
def alarm_events(): return ALARM_STORE.events()

@app.post('/api/alarms/{identifier}/ack')
def ack_alarm(identifier:int,body:AckRequest):
    operator=body.operator.strip()
    if not operator: raise HTTPException(400,'Operatör adı gerekli')
    try: ALARM_STORE.acknowledge(identifier,operator)
    except KeyError: raise HTTPException(404,'Alarm bulunamadı')
    return dict(success=True)

class SimulationEventRequest(BaseModel):
    bit:int=Field(ge=0,le=15)
    active:bool
    operator:str=Field(min_length=1,max_length=80)

def require_local_test(request):
    if not CONTROLS.enabled:raise HTTPException(409,'Manuel simülasyon testleri kapalı')
    if request.client and request.client.host not in ('127.0.0.1','::1','testclient'):raise HTTPException(403,'Test kontrolü yalnızca yerel bilgisayarda kullanılabilir')
    origin=request.headers.get('origin')
    if origin and origin!=str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Test isteğinin kaynağı farklı')

@app.post('/api/simulation/{unit}/event')
def simulation_event(unit:int,body:SimulationEventRequest,request:Request):
    require_local_test(request)
    if not body.operator.strip():raise HTTPException(400,'Operatör adı gerekli')
    try:command=CONTROLS.change(unit,body.bit,body.active,body.operator.strip())
    except ValueError as e:raise HTTPException(400,str(e))
    return dict(success=True,status='REQUESTED',command=command,message='İstek kaydedildi; gerçekleşme yalnızca IEC104 verisiyle doğrulanır.')

@app.post('/api/simulation/{unit}/clear')
def simulation_clear(unit:int,body:AckRequest,request:Request):
    require_local_test(request)
    if not body.operator.strip():raise HTTPException(400,'Operatör adı gerekli')
    try:command=CONTROLS.change(unit,None,False,body.operator.strip())
    except ValueError as e:raise HTTPException(400,str(e))
    return dict(success=True,status='REQUESTED',command=command)

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host=CFG['web_host'],port=CFG['web_port'])
