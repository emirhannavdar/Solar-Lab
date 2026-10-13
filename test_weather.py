import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from simulator import Plant,load_config
from weather_service import WeatherService

def fixture(now):
    h=int(now//3600)*3600
    return dict(current=dict(time=now-60,temperature_2m=22,wind_speed_10m=1,cloud_cover=80,weather_code=3,global_tilted_irradiance_instant=600,is_day=1),
      hourly=dict(time=[h-3600,h,h+3600],temperature_2m=[20,22,24],wind_speed_10m=[1,1,1],cloud_cover=[80,80,80],weather_code=[3,3,3],global_tilted_irradiance_instant=[0,800,400]),
      daily=dict(sunrise=[h-7200],sunset=[h+7200]),hourly_units={'temperature_2m':'°C','wind_speed_10m':'m/s','global_tilted_irradiance_instant':'W/m²'})

class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cfg=load_config();self.cfg['state_file']=str(Path(self.temp.name)/'state.json')
        self.cfg['simulation_control_file']=str(Path(self.temp.name)/'controls.json')
        self.cfg['weather']['cache_file']=str(Path(self.temp.name)/'weather.json')
        self.now=time.time();self.raw=fixture(self.now);self.w=WeatherService(self.cfg)
    def fetch_fixture(self,raw=None):
        payload=json.dumps(raw or self.raw).encode()
        with patch('weather_service.urllib.request.urlopen',return_value=io.BytesIO(payload)):
            self.w.fetch()
    def test_params_and_fresh_interpolation(self):
        self.fetch_fixture();self.assertEqual(self.w.snapshot()['status'],'FRESH')
        self.assertEqual(self.w.params()['azimuth'],0);self.assertEqual(self.w.params()['tilt'],30)
        self.assertEqual(self.w.params()['timezone'],'Europe/Istanbul')
        t=self.raw['hourly']['time'][0]+1800
        sample=self.w.sample(t);self.assertEqual(sample['global_tilted_irradiance_instant'],400);self.assertEqual(sample['temperature_2m'],21)
    def test_night_gate_and_outside_horizon(self):
        raw=copy.deepcopy(self.raw);h=raw['hourly']['time'][1]
        raw['daily']['sunrise']=[h];raw['daily']['sunset']=[h+1800]
        self.fetch_fixture(raw)
        self.assertEqual(self.w.sample(h-1800)['global_tilted_irradiance_instant'],0)
        self.assertIsNone(self.w.sample(h+7200))
    def test_network_failure_preserves_recent_cache_but_expires(self):
        self.fetch_fixture()
        with patch('weather_service.urllib.request.urlopen',side_effect=TimeoutError):self.w.fetch()
        self.assertEqual(self.w.snapshot()['status'],'CACHED')
        self.assertIsNotNone(self.w.sample(self.now))
        self.assertEqual(self.w.snapshot(self.now+2000)['status'],'STALE')
        self.assertIsNone(self.w.sample(self.now,wall_now=self.now+2000))
    def test_invalid_null_unit_and_time_are_rejected(self):
        for mutate in [lambda d:d['current'].update(temperature_2m=None),lambda d:d['hourly_units'].update(wind_speed_10m='km/h'),lambda d:d['current'].update(time=self.now-7200)]:
            raw=copy.deepcopy(self.raw);mutate(raw);self.fetch_fixture(raw)
            self.assertFalse(self.w.snapshot()['usable'])
    def test_production_changes_with_irradiance_not_cloud_double_count(self):
        self.fetch_fixture();p=Plant(self.cfg,persist=False)
        p.now=p.now.fromtimestamp(self.raw['hourly']['time'][1],p.now.tzinfo)
        p.refresh(0);power=p.devices[1]['power_kw'];self.assertGreater(power,0)
        raw=copy.deepcopy(self.raw);raw['hourly']['cloud_cover']=[0,0,0];self.fetch_fixture(raw);p.refresh(0)
        self.assertAlmostEqual(p.devices[1]['power_kw'],power)
        raw['hourly']['global_tilted_irradiance_instant']=[0,400,200];self.fetch_fixture(raw);p.refresh(0)
        self.assertLess(p.devices[1]['power_kw'],power)
        self.assertAlmostEqual(p.devices[1]['dc_power_kw']*p.devices[1]['efficiency']/100,p.devices[1]['power_kw'])
    def test_missing_weather_standby_and_cached_location_guard(self):
        p=Plant(self.cfg,persist=False);self.assertEqual(p.devices[1]['status'],8);self.assertEqual(p.devices[1]['power_kw'],0)
        self.fetch_fixture();other=copy.deepcopy(self.cfg);other['weather']['tilt']=45
        self.assertFalse(WeatherService(other).snapshot()['usable'])

if __name__=='__main__':unittest.main(verbosity=2)
