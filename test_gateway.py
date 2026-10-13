"""TEST ONLY: Modbus -> IEC104 gateway for integration verification.
In the real workflow Telediagram must replace this program. Never start both.
"""
import argparse
import json
from pathlib import Path
import socket
import struct
import time
import c104
from signals import mappings, SIGNALS

ROOT=Path(__file__).resolve().parent

def exact(sock,count):
    data=b''
    while len(data)<count:
        chunk=sock.recv(count-len(data))
        if not chunk: raise ConnectionError('Modbus bağlantısı kapandı')
        data+=chunk
    return data

def read_bank(sock,unit,transaction):
    sock.sendall(struct.pack('>HHHBBHH',transaction,0,6,unit,3,0,len(SIGNALS)*2))
    tid,protocol,length,uid=struct.unpack('>HHHB',exact(sock,7))
    if tid!=transaction or protocol!=0 or uid!=unit or not 2<=length<=254:
        raise ValueError('Geçersiz Modbus başlığı')
    body=exact(sock,length-1)
    if body[0]!=3 or len(body)!=2+len(SIGNALS)*4 or body[1]!=len(SIGNALS)*4:
        raise ValueError(f'Modbus hata yanıtı: {body.hex()}')
    return dict(zip([s[0] for s in SIGNALS],struct.unpack('>'+ 'f'*len(SIGNALS),body[2:])))

def run(host):
    cfg=json.loads((ROOT/'config.json').read_text())
    server=c104.Server(ip='127.0.0.1',port=cfg['iec_port'],tick_rate_ms=100)
    station=server.add_station(common_address=cfg['common_address'])
    points=[]
    for row in mappings():
        point=station.add_point(io_address=row['ioa'],type=getattr(c104.Type,cfg['iec_type']),report_ms=1000)
        point.info=c104.ShortInfo(actual=0.0,quality=c104.Quality.Invalid)
        points.append((row,point))
    server.start()
    print('TEST gateway aktif. Gerçek kullanımda kapatıp Telediagram çalıştırın.')
    transaction=0
    try:
        while True:
            try:
                with socket.create_connection((host,cfg['modbus_port']),timeout=3) as sock:
                    while True:
                        banks={}
                        for unit in range(1,12):
                            transaction=(transaction+1)%65536
                            banks[unit]=read_bank(sock,unit,transaction)
                        for row,point in points:
                            point.info=c104.ShortInfo(actual=banks[row['unit_id']][row['key']])
                        time.sleep(1)
            except (OSError,ValueError,ConnectionError) as exc:
                for _,point in points:
                    point.info=c104.ShortInfo(actual=float(point.value),quality=c104.Quality.Invalid)
                print(f'Modbus okunamadı: {exc}');time.sleep(2)
    finally: server.stop()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--modbus-host',default='127.0.0.1')
    args=parser.parse_args()
    try: run(args.modbus_host)
    except KeyboardInterrupt: pass
