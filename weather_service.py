import bisect
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request

URL='https://api.open-meteo.com/v1/forecast'
FIELDS=('temperature_2m','wind_speed_10m','cloud_cover','weather_code','global_tilted_irradiance_instant')
WMO={0:'Açık',1:'Az bulutlu',2:'Parçalı bulutlu',3:'Kapalı',45:'Sis',48:'Kırağılı sis',51:'Hafif çisenti',53:'Çisenti',55:'Yoğun çisenti',56:'Donan çisenti',57:'Yoğun donan çisenti',61:'Hafif yağmur',63:'Yağmur',65:'Yoğun yağmur',66:'Donan yağmur',67:'Yoğun donan yağmur',71:'Hafif kar',73:'Kar',75:'Yoğun kar',77:'Kar taneleri',80:'Hafif sağanak',81:'Sağanak',82:'Şiddetli sağanak',85:'Kar sağanağı',86:'Yoğun kar sağanağı',95:'Gök gürültülü',96:'Dolu ve gök gürültüsü',99:'Şiddetli dolu ve gök gürültüsü'}

def finite(value,minimum,maximum):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and minimum<=value<=maximum

def validate_values(row):
    limits={'temperature_2m':(-80,65),'wind_speed_10m':(0,100),'cloud_cover':(0,100),'weather_code':(0,99),'global_tilted_irradiance_instant':(0,2000)}
    if not all(finite(row.get(k),*limits[k]) for k in FIELDS):raise ValueError('Hava verisinde eksik/geçersiz sayı')
    if row['weather_code']!=int(row['weather_code']):raise ValueError('Geçersiz WMO kodu')

class WeatherService:
    def __init__(self,cfg,root=None):
        self.cfg=cfg
        self.options=cfg.get('weather',{})
        self.enabled=self.options.get('enabled',False)
        self.root=Path(root or Path(__file__).resolve().parent)
        self.path=self.root/self.options.get('cache_file','weather_cache.json')
        self.profile={k:self.options.get(k,d) for k,d in [('latitude',39.79),('longitude',32.80),('tilt',30),('azimuth',0)]}
        if not finite(self.profile['latitude'],-90,90) or not finite(self.profile['longitude'],-180,180) or not finite(self.profile['tilt'],0,90) or not finite(self.profile['azimuth'],-180,180):raise ValueError('Hava konum/panel açısı geçersiz')
        self.memo=None;self.stamp=None
    def params(self):
        return dict(**self.profile,timezone='Europe/Istanbul',timeformat='unixtime',wind_speed_unit='ms',
            current=','.join(FIELDS)+',is_day',hourly=','.join(FIELDS),daily='sunrise,sunset',forecast_days=2)
    def read(self):
        try:
            stamp=self.path.stat().st_mtime_ns
            if stamp!=self.stamp:
                data=json.loads(self.path.read_text(encoding='utf-8'))
                self.memo=data if data.get('schema')==1 and data.get('profile')==self.profile else None
                self.stamp=stamp
        except (OSError,ValueError):self.memo=None;self.stamp=None
        return self.memo or {}
    def save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(self.path)
        self.memo=None;self.stamp=None
    def fetch(self):
        if not self.enabled:return
        try:
            req=urllib.request.Request(URL+'?'+urllib.parse.urlencode(self.params()),headers={'User-Agent':'SolarLab/2.1'})
            with urllib.request.urlopen(req,timeout=self.options.get('timeout_seconds',10)) as response:
                raw=json.load(response)
            current=raw['current'];validate_values(current)
            if current.get('is_day') not in (0,1) or not finite(current.get('time'),0,1e12):raise ValueError('Hava zamanı/gündüz bilgisi geçersiz')
            hourly=raw['hourly'];times=hourly['time']
            if len(times)<2 or any(not finite(t,0,1e12) for t in times) or any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Hava saat dizisi geçersiz')
            if any(len(hourly.get(k,[]))!=len(times) for k in FIELDS):raise ValueError('Hava dizilerinin uzunlukları farklı')
            for i in range(len(times)):validate_values({k:hourly[k][i] for k in FIELDS})
            daily=raw['daily']
            if len(daily['sunrise'])!=len(daily['sunset']) or not daily['sunrise']:raise ValueError('Güneş saatleri eksik')
            if any(not finite(a,0,1e12) or not finite(b,0,1e12) or a>=b for a,b in zip(daily['sunrise'],daily['sunset'])):raise ValueError('Güneş saatleri geçersiz')
            now=time.time()
            if not -300<=now-current['time']<=3600 or not times[0]<=now<=times[-1]:raise ValueError('API hava zamanı sistem saatiyle uyuşmuyor')
            units=raw.get('hourly_units',{})
            if units.get('global_tilted_irradiance_instant')!='W/m²' or units.get('temperature_2m')!='°C' or units.get('wind_speed_10m')!='m/s':raise ValueError('Beklenmeyen hava birimleri')
            data=dict(schema=1,profile=self.profile,provider='Open-Meteo',fetched_at=now,current=current,hourly=hourly,
                daily=daily,last_error=None,last_attempt_at=now)
            self.save(data)
        except Exception as exc:
            # Keep recent valid data. Do not expose provider URLs, credentials or raw responses.
            data=dict(self.read());data.update(schema=1,profile=self.profile,last_error=type(exc).__name__,last_attempt_at=time.time())
            self.save(data)
    def snapshot(self,now=None):
        now=time.time() if now is None else now
        data=self.read();age=now-data['fetched_at'] if data.get('fetched_at') else None
        current=data.get('current',{})
        source_age=now-current.get('time',0) if current else None
        usable=bool(self.enabled and age is not None and -300<=age<=self.options.get('max_age_seconds',1800) and source_age is not None and -300<=source_age<=3600)
        status='DISABLED' if not self.enabled else 'UNAVAILABLE' if age is None else 'STALE' if not usable else 'CACHED' if data.get('last_error') else 'FRESH'
        try:
            if usable:validate_values(current)
        except ValueError:usable=False;status='INVALID'
        return dict(provider='Open-Meteo',location=self.options.get('location','Ankara / Gölbaşı'),profile=self.profile,
            status=status,usable=usable,age_seconds=round(age,1) if age is not None else None,
            fetched_at=datetime.fromtimestamp(data['fetched_at'],timezone.utc).isoformat() if data.get('fetched_at') else None,
            weather_time=datetime.fromtimestamp(current['time'],timezone.utc).isoformat() if current.get('time') else None,
            current=current if usable else None,last_error=data.get('last_error'),description=WMO.get(current.get('weather_code'),'Bilinmiyor') if usable else 'Hava verisi yok / eski',
            attribution='Weather data by Open-Meteo.com',is_modelled=True)
    def sample(self,timestamp,wall_now=None):
        snap=self.snapshot(wall_now)
        if not snap['usable']:return None
        data=self.read();h=data.get('hourly',{});times=h.get('time',[])
        if len(times)<2 or not times[0]<=timestamp<=times[-1]:return None
        j=max(0,min(len(times)-2,bisect.bisect_right(times,timestamp)-1))
        fraction=(timestamp-times[j])/(times[j+1]-times[j])
        try:
            row={k:h[k][j]+fraction*(h[k][j+1]-h[k][j]) for k in FIELDS if k!='weather_code'}
            row['weather_code']=h['weather_code'][j];validate_values(row)
            daylight=any(a<=timestamp<b for a,b in zip(data['daily']['sunrise'],data['daily']['sunset']))
            if not daylight:row['global_tilted_irradiance_instant']=0.0
            row['is_day']=int(daylight)
            return row
        except (KeyError,IndexError,ValueError,TypeError):return None
