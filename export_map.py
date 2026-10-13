import csv
import json
from pathlib import Path
from signals import mappings
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    rows=list(mappings())
    for row in rows:
        row['common_address']=cfg['common_address']
        row['iec_type']=cfg['iec_type']
        row['type_id']=13 if cfg['iec_type']=='M_ME_NC_1' else 36
    with (ROOT/'point_map.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (ROOT/'point_map.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(rows)} nokta yazıldı: point_map.csv / point_map.json')
