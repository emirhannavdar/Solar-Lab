"""10 inverter + analyzer simulator. One TCP port, read-only FC03/FC04.
The Modbus transport uses only Python's standard library; no pymodbus version coupling.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import random
import struct
import time
from signals import SIGNALS, ANALYZER_KEYS
from sunspec import BASE, native_registers, FAULT_BITS, OFF_BITS, DEFINED_MASK
from simulation_controls import SimulationControls
from weather_service import WeatherService

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=3))

def load_config(path=ROOT / 'config.json'):
    return json.loads(Path(path).read_text(encoding='utf-8'))

class Plant:
    def __init__(self, cfg, persist=True):
        self.cfg = cfg
        self.weather=WeatherService(cfg,ROOT)
        if self.weather.enabled and (cfg['mode']!='realtime' or cfg['time_scale']!=1):
            raise ValueError('Canlı hava için mode=realtime ve time_scale=1 gerekli')
        self.rng = random.Random(cfg['seed'])
        self.rated = float(cfg['inverter_rated_kw'])
        self.panel=cfg.get('panel',{})
        self.dc_rated=(self.panel['power_w']*self.panel['series_modules']*self.panel['parallel_strings']/1000 if self.panel else self.rated*cfg['dc_ac_ratio'])
        if self.rated <= 0 or float(cfg['time_scale']) <= 0 or float(cfg['dc_ac_ratio']) <= 0:
            raise ValueError('Nominal güç, DC/AC oranı ve zaman ölçeği pozitif olmalı')
        self.now = datetime.now(TZ) if cfg['mode'] == 'realtime' else datetime.fromisoformat(cfg['demo_start'])
        if self.now.tzinfo is None:
            raise ValueError('demo_start saat dilimi içermeli: +03:00')
        if cfg['mode'] not in ('demo', 'realtime'):
            raise ValueError('mode: demo veya realtime olmalı')
        self.persist = persist
        self.path = ROOT / cfg.get('state_file', 'state.json')
        self.daily = [0.0]*10
        self.total = [120000.0+i*2300 for i in range(10)]
        self.temps = [25.0]*10
        self.cloud = 0.88
        self.devices = {}
        self.previous_power = [0.0]*10
        self.controls=SimulationControls(ROOT/cfg.get('simulation_control_file','simulation_control_v2.json'),cfg.get('simulation_actions_enabled',False))
        self.was_stopped=[False]*10
        self.starting=[0.0]*10
        self.thermal_latched=[False]*10
        self.cold_latched=[False]*10
        self.last_saved = time.monotonic()
        if persist and self.path.exists():
            saved = json.loads(self.path.read_text())
            if len(saved['total']) != 10 or len(saved['daily']) != 10:
                raise ValueError('state.json 10 invertör içermeli')
            self.total = saved['total']
            for name in ('temps','thermal_latched','cold_latched','was_stopped','starting'):
                values=saved.get(name)
                if isinstance(values,list) and len(values)==10:setattr(self,name,values)
            if cfg['mode'] == 'demo' and saved.get('mode') == 'demo':
                self.now = datetime.fromisoformat(saved['simulation_time'])
            if saved['date'] == self.now.date().isoformat():
                self.daily = saved['daily']
        self.refresh(0)
        self.previous_power = [self.devices[u]['power_kw'] for u in range(1,11)]
        if not (persist and self.path.exists()):
            target = self.now
            self.now = target.replace(hour=0, minute=0, second=0, microsecond=0)
            self.refresh(0)
            self.previous_power = [self.devices[u]['power_kw'] for u in range(1,11)]
            self.step((target-self.now).total_seconds())

    def refresh(self, dt):
        hour = self.now.hour + self.now.minute/60 + self.now.second/3600
        # Illustrative summer day: sunrise 06:00, sunset 20:00. Not a site weather forecast.
        sun = max(0, math.sin(math.pi * (hour-6)/14)) if 6 < hour < 20 else 0
        ambient = 23+8*sun
        if dt:
            target_cloud = 0.83+0.10*math.sin(self.now.timestamp()/240)+0.04*math.sin(self.now.timestamp()/67)
            self.cloud += (target_cloud-self.cloud)*(1-math.exp(-dt/40))
        irradiance = 1000*sun*self.cloud
        weather_sample=self.weather.sample(self.now.timestamp()) if self.weather.enabled else None
        weather_missing=self.weather.enabled and weather_sample is None
        if self.weather.enabled:
            irradiance=weather_sample['global_tilted_irradiance_instant'] if weather_sample else 0.0
            ambient=weather_sample['temperature_2m'] if weather_sample else 25.0
        wind=weather_sample['wind_speed_10m'] if weather_sample else 1.0
        voltages = [230+1.6*math.sin(self.now.timestamp()/120+i*1.7) for i in range(3)]
        frequency = 50+0.025*math.sin(self.now.timestamp()/90)
        commanded=self.controls.read().get('units',{}) if self.controls.enabled else {}
        for i in range(10):
            unit = i+1
            shade = 0.965+0.03*math.sin(i*1.9)  # Individual array production differences.
            # Empirical NOCT/wind thermal approximation, not a manufacturer thermal solver.
            cell_temp=ambient+(self.panel.get('noct_c',43)-20)*irradiance/800/max(.5,1+.08*(wind-1))
            gamma=self.panel.get('pmax_temp_coefficient',-.0035)
            dc=self.dc_rated*(irradiance/1000)*shade*max(0,1+gamma*(cell_temp-25))
            bits=set(commanded.get(str(unit),{}).get('bits',[])) & set(range(16))
            if 7 in bits:self.temps[i]=max(self.temps[i],85.0)
            if 13 in bits:self.temps[i]=min(self.temps[i],-25.0)
            self.thermal_latched[i]=self.temps[i]>75 if self.thermal_latched[i] else self.temps[i]>=85
            self.cold_latched[i]=self.temps[i]<-10 if self.cold_latched[i] else self.temps[i]<=-25
            if self.thermal_latched[i]:bits.add(7)
            if self.cold_latched[i]:bits.add(13)
            if unit in self.cfg.get('faulted_units',[]):bits.add(15)
            fault=bool(bits & FAULT_BITS)
            off=bool(bits & OFF_BITS)
            stopped=fault or off
            if self.was_stopped[i] and not stopped:self.starting[i]=float(self.cfg.get('restart_delay_seconds',5))
            self.was_stopped[i]=stopped
            if stopped:self.starting[i]=0
            elif dt:self.starting[i]=max(0,self.starting[i]-dt)
            restarting=self.starting[i]>0
            dc = max(0, dc) if irradiance > 15 and not stopped and not restarting else 0.0
            efficiency = (0.955+0.026*(1-math.exp(-dc/(self.rated*0.15)))) if dc else 0
            power = min(self.rated, dc*efficiency)
            throttled=power < dc*efficiency
            if 12 in bits:
                power*=0.8;throttled=True
            if power < dc*efficiency:  # MPPT curtails input at AC power limit.
                dc = power/efficiency
            pf = 0.995 if power else 1.0
            q = power*math.tan(math.acos(pf))
            s = math.hypot(power,q)
            dc_v = 680+35*sun+3*math.sin(i) if sun else 0.0
            if self.panel:
                dc_v=self.panel['series_modules']*self.panel['vmp_stc']*max(.3,1+self.panel.get('vmp_temp_coefficient_assumed',-.0033)*(cell_temp-25)) if irradiance>0 else 0.0
                if stopped and irradiance>0:
                    dc_v=self.panel['series_modules']*self.panel['voc_stc']*max(.3,1+self.panel['voc_temp_coefficient']*(cell_temp-25))
            if 3 in bits:dc_v=0.0
            if 1 in bits:dc_v=1100.0
            desired_temp = ambient+power/self.rated*28
            self.temps[i] += (desired_temp-self.temps[i])*(1-math.exp(-dt/180)) if dt else 0
            device_voltages=list(voltages)
            if 4 in bits:device_voltages=[0.0]*3
            elif 10 in bits:device_voltages=[260.0]*3
            elif 11 in bits:device_voltages=[180.0]*3
            device_frequency=51.5 if 8 in bits else 47.5 if 9 in bits else 0.0 if 4 in bits else frequency
            status=7 if fault else 1 if off else 3 if restarting else 8 if weather_missing else 5 if throttled and power else 4 if power else 2
            events=sum(1<<b for b in bits)
            self.devices[unit] = dict(power_kw=power,daily_kwh=self.daily[i],total_kwh=self.total[i],
                reactive_kvar=q,apparent_kva=s,power_factor=pf,v_l1n=device_voltages[0],v_l2n=device_voltages[1],v_l3n=device_voltages[2],
                i_l1=s*1000/(3*device_voltages[0]) if device_voltages[0] else 0,i_l2=s*1000/(3*device_voltages[1]) if device_voltages[1] else 0,i_l3=s*1000/(3*device_voltages[2]) if device_voltages[2] else 0,
                frequency=device_frequency,dc_voltage=dc_v,dc_current=dc*1000/dc_v if dc_v else 0,
                dc_power_kw=dc,temperature=self.temps[i],efficiency=efficiency*100,
                status=status,alarm_code=events & 65535,evt1_hi=events>>16,evt2_lo=0,evt2_hi=0,
                irradiance=irradiance*shade,rated_kw=self.rated,
                v_l1l2=math.sqrt(device_voltages[0]**2+device_voltages[1]**2+device_voltages[0]*device_voltages[1]),
                v_l2l3=math.sqrt(device_voltages[1]**2+device_voltages[2]**2+device_voltages[1]*device_voltages[2]),
                v_l3l1=math.sqrt(device_voltages[2]**2+device_voltages[0]**2+device_voltages[2]*device_voltages[0]))
        rows = [self.devices[u] for u in range(1,11)]
        analyzer = {k:rows[0][k] for k in ANALYZER_KEYS}
        for key in ('power_kw','daily_kwh','total_kwh','reactive_kvar','rated_kw','i_l1','i_l2','i_l3'):
            analyzer[key] = sum(row[key] for row in rows)
        analyzer['apparent_kva'] = math.hypot(analyzer['power_kw'],analyzer['reactive_kvar'])
        analyzer['power_factor'] = analyzer['power_kw']/analyzer['apparent_kva'] if analyzer['apparent_kva'] else 1
        analyzer['status'] = 7 if any(d['status']==7 for d in rows) else (4 if analyzer['power_kw'] else 8 if weather_missing else 2)
        analyzer['alarm_code']=0
        for d in rows:analyzer['alarm_code']|=d['alarm_code']
        analyzer.update(evt1_hi=0,evt2_lo=0,evt2_hi=0)
        # The analyzer is the common healthy grid bus. Local test faults do not change other units' grid.
        analyzer.update(v_l1n=voltages[0],v_l2n=voltages[1],v_l3n=voltages[2],frequency=frequency)
        for a,b in [(1,2),(2,3),(3,1)]:analyzer[f'v_l{a}l{b}']=math.sqrt(voltages[a-1]**2+voltages[b-1]**2+voltages[a-1]*voltages[b-1])
        self.devices[11] = analyzer

    def step(self, seconds):
        # Small substeps preserve integration and midnight semantics under acceleration.
        while seconds > 1e-8:
            midnight = (self.now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
            dt = min(seconds, 10, (midnight-self.now).total_seconds())
            self.now += timedelta(seconds=dt)
            self.refresh(dt)
            for i in range(10):
                p = self.devices[i+1]['power_kw']
                delta = (self.previous_power[i]+p)*0.5*dt/3600
                self.daily[i] += delta
                self.total[i] += delta
                self.previous_power[i] = p
            if self.now == midnight:
                self.daily = [0.0]*10
            seconds -= dt
        self.refresh(0)

    def registers(self, unit):
        row = self.devices[unit]
        words=[]
        for key, _, _ in SIGNALS:
            # Unsupported analyzer fields remain 0 in the bank, but are excluded from point map.
            words.extend(struct.unpack('>HH',struct.pack('>f',row.get(key,0))))
        return words

    def save(self):
        if not self.persist:
            return
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(mode=self.cfg['mode'],date=self.now.date().isoformat(),
            simulation_time=self.now.isoformat(),daily=self.daily,total=self.total,temps=self.temps,
            thermal_latched=self.thermal_latched,cold_latched=self.cold_latched,
            was_stopped=self.was_stopped,starting=self.starting)),encoding='utf-8')
        temp.replace(self.path)

async def serve_client(reader, writer, plant):
    try:
        while True:
            header = await asyncio.wait_for(reader.readexactly(7),30)
            transaction, protocol, length, unit = struct.unpack('>HHHB',header)
            if protocol != 0 or not 2 <= length <= 254:
                break
            pdu = await asyncio.wait_for(reader.readexactly(length-1),10)
            fc = pdu[0]
            error = None
            if fc not in (3,4): error=1
            elif unit not in plant.devices: error=11
            elif len(pdu)!=5: error=3
            else:
                start,count=struct.unpack('>HH',pdu[1:])
                if not 1 <= count <= 125: error=3
                elif not (start+count <= len(SIGNALS)*2 or (unit<=10 and BASE<=start and start+count<=BASE+len(native_registers(plant.devices[unit],unit)))): error=2
            if error:
                response=bytes([fc|0x80,error])
            else:
                words=(native_registers(plant.devices[unit],unit)[start-BASE:start-BASE+count] if start>=BASE else plant.registers(unit)[start:start+count])
                response=bytes([fc,count*2])+struct.pack('>'+ 'H'*count,*words)
            writer.write(struct.pack('>HHHB',transaction,0,len(response)+1,unit)+response)
            await writer.drain()
    except (asyncio.IncompleteReadError,TimeoutError,ConnectionError):
        pass
    finally:
        writer.close()
        try: await writer.wait_closed()
        except ConnectionError: pass

async def main(cfg):
    plant=Plant(cfg)
    async def update_weather():
        while True:
            await asyncio.to_thread(plant.weather.fetch)
            await asyncio.sleep(max(60,cfg.get('weather',{}).get('refresh_seconds',300)))
    weather_task=asyncio.create_task(update_weather()) if plant.weather.enabled else None
    server=await asyncio.start_server(lambda r,w:serve_client(r,w,plant),cfg['modbus_host'],cfg['modbus_port'])
    print(f"Modbus {cfg['modbus_host']}:{cfg['modbus_port']} | Unit 1–10 invertör, 11 analizör | {cfg['mode']}")
    last=time.monotonic()
    try:
        async with server:
            while True:
                await asyncio.sleep(1)
                now=time.monotonic()
                plant.step((now-last)*cfg['time_scale']); last=now
                if now-plant.last_saved>=10:
                    plant.save(); plant.last_saved=now
    finally:
        if weather_task:
            weather_task.cancel()
            try:await weather_task
            except asyncio.CancelledError:pass
        plant.save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',default=str(ROOT/'config.json'))
    args=parser.parse_args()
    try: asyncio.run(main(load_config(args.config)))
    except KeyboardInterrupt: pass
