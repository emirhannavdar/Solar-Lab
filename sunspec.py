"""SunSpec Model 103 native register encoding and exact event/state definitions.
Sources: https://github.com/sunspec/models (model_1.json, model_103.json).
Simulation reactions below are Solar Lab policy, not prescribed by SunSpec.
"""
import json
import math
import struct
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE=40000  # Zero-based Modbus PDU address; signature occupies 40000..40001.
MODEL1=json.loads((ROOT/'sunspec_model_1.json').read_text())
MODEL103=json.loads((ROOT/'sunspec_model_103.json').read_text())
STATES={1:'Kapalı',2:'Uyku / gece',3:'Başlatılıyor',4:'MPPT / üretimde',5:'Güç sınırlandırılıyor',6:'Kapanıyor',7:'Arıza',8:'Beklemede'}
LABELS=['Toprak kaçağı','DC aşırı gerilim','AC bağlantısı kesik','DC bağlantısı kesik','Şebeke bağlantısı kesik','Kabin açık','Manuel durdurma','Aşırı sıcaklık','Yüksek frekans','Düşük frekans','AC aşırı gerilim','AC düşük gerilim','String sigortası arızası','Düşük sıcaklık','Bellek hatası','Donanım testi hatası']
FAULT_BITS={0,1,4,7,8,9,10,11,13,14,15}
OFF_BITS={2,3,6}
EVENTS=[dict(bit=p['value'],key=p['name'],mask=1<<p['value'],label=LABELS[p['value']],
    severity='WARNING' if p['value'] in {5,12} else ('INFO' if p['value'] in OFF_BITS else 'CRITICAL'),
    reaction='FAULT' if p['value'] in FAULT_BITS else ('OFF' if p['value'] in OFF_BITS else ('DERATE' if p['value']==12 else 'WARNING')))
    for p in next(p for p in MODEL103['group']['points'] if p['name']=='Evt1')['symbols']]
EVENT_BY_BIT={p['bit']:p for p in EVENTS}
DEFINED_MASK=sum(p['mask'] for p in EVENTS)

def combine(lo,hi):
    if lo is None or hi is None: return None
    if any(not math.isfinite(v) or v!=int(v) or not 0<=v<=65535 for v in (lo,hi)): return None
    return int(lo)|(int(hi)<<16)

def event_rows(unit):
    for e in EVENTS:
        # Internal history identifiers, NOT new IEC104 points.
        yield dict(**e,unit_id=unit,ioa=unit*100000+e['bit'],signal_ioa=unit*1000+20,
            source='SunSpec Evt1 via IEC104',action=e['reaction'],signal_key='alarm_code',engineering_unit='')

def native_map():
    addr=BASE+2
    for model in (MODEL1,MODEL103):
        for p in model['group']['points']:
            yield dict(model=model['id'],key=p['name'],pdu_address=addr,register_count=p['size'],data_type=p['type'])
            addr+=p['size']
    yield dict(model=65535,key='END_ID',pdu_address=addr,register_count=1,data_type='uint16')
    yield dict(model=65535,key='END_LENGTH',pdu_address=addr+1,register_count=1,data_type='uint16')

def encode_point(p,value):
    size=p['size'];typ=p['type']
    if typ=='string':
        b=str(value or '').encode('ascii','replace')[:size*2].ljust(size*2,b'\0')
        return list(struct.unpack('>'+'H'*size,b))
    if value is None:
        if typ in ('int16','sunssf'):return [0x8000]
        return [0xffff]*size
    value=int(value)
    if size==2:
        if not 0<=value<=0xffffffff: raise ValueError('SunSpec uint32 range')
        return [value>>16,value&65535]
    if typ in ('int16','sunssf'):
        if not -32767<=value<=32767:raise ValueError('SunSpec int16 range')
        return [value&65535]
    if not 0<=value<=65534:raise ValueError('SunSpec uint16 range')
    return [value]

def native_registers(row,unit):
    # All required measurements have explicit scale factors. No FLOAT32 bitfields.
    values={'Mn':'SolarLab','Md':'SIM-100K-3P','Opt':'Model103','Vr':'2.0','SN':f'SOLARLAB-{unit:02}','DA':unit,'Pad':0,
      'A':round(sum(row[f'i_l{i}'] for i in (1,2,3))*10),'A_SF':-1,
      'V_SF':-1,'W':round(row['power_kw']*100),'W_SF':1,
      'Hz':round(row['frequency']*100),'Hz_SF':-2,'VA':round(row['apparent_kva']*100),'VA_SF':1,
      'VAr':round(row['reactive_kvar']*100),'VAr_SF':1,'PF':round(row['power_factor']*10000),'PF_SF':-2,
      'WH':round(row['total_kwh']*1000)&0xffffffff,'WH_SF':0,'DCA':round(row['dc_current']*10),'DCA_SF':-1,
      'DCV':round(row['dc_voltage']*10),'DCV_SF':-1,'DCW':round(row['dc_power_kw']*100),'DCW_SF':1,
      'TmpCab':round(row['temperature']*10),'Tmp_SF':-1,'St':int(row['status']),
      'Evt1':int(row['alarm_code'])|(int(row['evt1_hi'])<<16),'Evt2':int(row['evt2_lo'])|(int(row['evt2_hi'])<<16)}
    for i,suffix in enumerate(['A','B','C'],1):
        values['Aph'+suffix]=round(row[f'i_l{i}']*10)
        values['PhVph'+suffix]=round(row[f'v_l{i}n']*10)
    for key,source in [('PPVphAB','v_l1l2'),('PPVphBC','v_l2l3'),('PPVphCA','v_l3l1')]:values[key]=round(row[source]*10)
    words=[0x5375,0x6e53]
    for model in (MODEL1,MODEL103):
        length=sum(p['size'] for p in model['group']['points'])-2
        for p in model['group']['points']:
            value=model['id'] if p['name']=='ID' else length if p['name']=='L' else values.get(p['name'])
            words.extend(encode_point(p,value))
    return words+[65535,0]
