"""Read-only IEC104 diagnostic; standard library only. Stop receiver first."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import struct
import time

def decode(frame):
    if frame[2] & 1 or len(frame) < 12:
        return {}
    a = frame[6:]
    result = dict(type=a[0], count=a[1] & 127, sequential=bool(a[1]&128),
                  cause=a[2]&63, common_address=int.from_bytes(a[4:6], 'little'))
    if a[0] not in (13, 36):
        return result
    p, points, base = 6, [], None
    for i in range(result['count']):
        if i == 0 or not result['sequential']:
            if p+3 > len(a):
                result['decode_error']='IOA truncated'; break
            base=int.from_bytes(a[p:p+3], 'little'); p+=3
        ioa=base+i if result['sequential'] else base
        size=12 if a[0]==36 else 5
        if p+size > len(a):
            result['decode_error']='Measurement truncated'; break
        points.append(dict(ioa=ioa,value=struct.unpack_from('<f',a,p)[0],quality=a[p+4]))
        p+=size
    result['points']=points
    result['trailing_bytes']=len(a)-p
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='192.168.1.150')
    parser.add_argument('--port',type=int,default=2404)
    parser.add_argument('--ca',type=int,default=1)
    parser.add_argument('--seconds',type=float,default=25)
    args=parser.parse_args()
    out=Path(__file__).resolve().parent/'iec104_teshis.json'
    report=dict(endpoint=f'{args.host}:{args.port}',common_address=args.ca,
                started_at=datetime.now(timezone.utc).isoformat(),frames=[],received_ioas=[])
    seen=Counter()
    ns=nr=0
    try:
        print(f'RTU {args.host}:{args.port} - {args.seconds:g} saniye kayit')
        with socket.create_connection((args.host,args.port),timeout=5) as sock:
            sock.settimeout(0.5)
            def send(payload):
                sock.sendall(payload)
                report['frames'].append(dict(direction='TX',hex=payload.hex(),time=datetime.now(timezone.utc).isoformat()))
            def gi():
                nonlocal ns
                asdu=bytes([100,1,6,0])+args.ca.to_bytes(2,'little')+bytes([0,0,0,20])
                send(bytes([104,4+len(asdu)])+struct.pack('<HH',ns<<1,nr<<1)+asdu)
                ns=(ns+1)%32768
            send(bytes.fromhex('680407000000'))
            start=time.monotonic(); last_gi=None; buffer=b''
            while time.monotonic()-start < args.seconds:
                if last_gi is not None and time.monotonic()-last_gi > 10:
                    gi(); last_gi=time.monotonic()
                try: chunk=sock.recv(4096)
                except socket.timeout: continue
                if not chunk: raise ConnectionError('RTU baglantiyi kapatti')
                buffer+=chunk
                while len(buffer)>=2:
                    if buffer[0]!=104: raise ValueError('Invalid IEC104 frame start')
                    length=buffer[1]+2
                    if len(buffer)<length: break
                    frame,buffer=buffer[:length],buffer[length:]
                    parsed=decode(frame)
                    report['frames'].append(dict(direction='RX',hex=frame.hex(),time=datetime.now(timezone.utc).isoformat(),decoded=parsed))
                    for point in parsed.get('points',[]): seen[point['ioa']]+=1
                    if frame[2] & 1 == 0:
                        nr=((int.from_bytes(frame[2:4],'little')>>1)+1)%32768
                        send(bytes([104,4,1,0])+struct.pack('<H',nr<<1))
                    elif frame[2]==11 and last_gi is None:
                        gi(); last_gi=time.monotonic()
                    elif frame[2]==67:
                        send(bytes.fromhex('680483000000'))
    except (OSError,ValueError) as exc:
        report['error']=str(exc)
        print('Hata:',exc)
    finally:
        report['received_ioas']=sorted(seen)
        report['receive_counts']=dict(seen)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Gelen IOA:', ', '.join(map(str,sorted(seen))) or 'Yok')
        print('Kayit:',out)

if __name__=='__main__': main()
