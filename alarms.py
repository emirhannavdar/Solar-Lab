"""RTU alarm catalogue and durable occurrence/event journal (no threshold decisions)."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from signals import SIGNALS

def utc(): return datetime.now(timezone.utc).isoformat()

from sunspec import event_rows
CATALOG=[row for unit in range(1,11) for row in event_rows(unit)]
BY_IOA={r['ioa']:r for r in CATALOG}

class AlarmStore:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS observations(ioa INTEGER PRIMARY KEY, active INTEGER, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS occurrences(id INTEGER PRIMARY KEY, ioa INTEGER, unit_id INTEGER,
          label TEXT, severity TEXT, raised_at TEXT, cleared_at TEXT, acknowledged_at TEXT,
          acknowledged_by TEXT, initial_observation INTEGER DEFAULT 0);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_alarm ON occurrences(ioa) WHERE cleared_at IS NULL;
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, occurrence_id INTEGER, ioa INTEGER,
          kind TEXT, received_at TEXT, source_time TEXT, details TEXT);
        ''')
        self.db.commit()
    def receive(self,ioa,active,received_at,source_time=None):
        row=BY_IOA[ioa]
        with self.lock,self.db:
            prev=self.db.execute('SELECT active FROM observations WHERE ioa=?',(ioa,)).fetchone()
            opened=self.db.execute('SELECT id FROM occurrences WHERE ioa=? AND cleared_at IS NULL',(ioa,)).fetchone()
            if prev is not None and bool(prev['active'])==bool(active) and bool(opened)==bool(active):return
            self.db.execute('INSERT INTO observations VALUES(?,?,?) ON CONFLICT(ioa) DO UPDATE SET active=excluded.active,updated_at=excluded.updated_at',(ioa,int(active),received_at))
            if active and opened is None:
                cur=self.db.execute('INSERT INTO occurrences(ioa,unit_id,label,severity,raised_at,initial_observation) VALUES(?,?,?,?,?,?)',
                    (ioa,row['unit_id'],row['label'],row['severity'],received_at,int(prev is None)))
                self.db.execute('INSERT INTO events(occurrence_id,ioa,kind,received_at,source_time,details) VALUES(?,?,?,?,?,?)',
                    (cur.lastrowid,ioa,'ACTIVE',received_at,source_time,'İlk gözlemde aktif; gerçek başlangıç zamanı bilinmiyor' if prev is None else 'SunSpec cihaz olayı aktif'))
            elif not active and opened is not None:
                self.db.execute('UPDATE occurrences SET cleared_at=? WHERE id=?',(received_at,opened['id']))
                self.db.execute('INSERT INTO events(occurrence_id,ioa,kind,received_at,source_time,details) VALUES(?,?,?,?,?,?)',
                    (opened['id'],ioa,'CLEARED',received_at,source_time,'SunSpec cihaz olayı normale döndü'))
    def acknowledge(self,identifier,operator):
        with self.lock,self.db:
            row=self.db.execute('SELECT * FROM occurrences WHERE id=?',(identifier,)).fetchone()
            if row is None: raise KeyError(identifier)
            if row['acknowledged_at'] is None:
                now=utc()
                self.db.execute('UPDATE occurrences SET acknowledged_at=?,acknowledged_by=? WHERE id=?',(now,operator,identifier))
                self.db.execute('INSERT INTO events(occurrence_id,ioa,kind,received_at,details) VALUES(?,?,?,?,?)',(identifier,row['ioa'],'ACKNOWLEDGED',now,operator))
    def history(self,limit=200,before=None):
        with self.lock:
            q='SELECT * FROM occurrences';params=[]
            if before is not None:q+=' WHERE id<?';params.append(before)
            q+=' ORDER BY id DESC LIMIT ?';params.append(limit)
            rows=[dict(r) for r in self.db.execute(q,params)]
            return rows
    def events(self,limit=200):
        with self.lock:return [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(limit,))]
    def open_rows(self):
        with self.lock:return {r['ioa']:dict(r) for r in self.db.execute('SELECT * FROM occurrences WHERE cleared_at IS NULL')}
    def close(self): self.db.close()

