"""Local lab commands only. Actual telemetry never comes from this file."""
import json
import threading
from datetime import datetime,timezone
from pathlib import Path
from sunspec import EVENT_BY_BIT

def utc():return datetime.now(timezone.utc).isoformat()

class SimulationControls:
    def __init__(self,path,enabled):
        self.path=Path(path);self.enabled=enabled;self.lock=threading.RLock()
    def read(self):
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):data={}
        if data.get('schema')!=2:return {'schema':2,'units':{},'commands':[]}
        return data
    def change(self,unit,bit,active,operator):
        if not self.enabled:raise ValueError('Manuel test kontrolleri kapalı')
        if unit not in range(1,11) or (bit is not None and bit not in EVENT_BY_BIT):raise ValueError('Unit veya alarm biti geçersiz')
        with self.lock:
            data=self.read();row=data.setdefault('units',{}).setdefault(str(unit),{'bits':[]})
            bits=set(row['bits'])
            if bit is None:bits.clear()
            elif active:bits.add(bit)
            else:bits.discard(bit)
            row['bits']=sorted(bits)
            command=dict(unit_id=unit,bit=bit,active=active,operator=operator,requested_at=utc())
            data['commands']=(data.get('commands',[])+[command])[-200:]
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
            return command
    def snapshot(self):
        with self.lock:return dict(enabled=self.enabled,**self.read())
