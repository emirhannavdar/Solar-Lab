'use strict';
const el=id=>document.getElementById(id), fmt=(v,n=1)=>v==null?'—':new Intl.NumberFormat('tr-TR',{minimumFractionDigits:n,maximumFractionDigits:n}).format(v);
let current=null,selected=null;
const value=(d,k)=>d?.signals[k]?.value??null;
const cards=el('cards');
for(let u=1;u<=10;u++){const card=document.createElement('article');card.className='card';card.id=`inv-${u}`;card.innerHTML=`<h3>İnvertör ${String(u).padStart(2,'0')}</h3><div class="state">Veri bekleniyor</div><div class="machine"><div class="screen"></div></div><label>Aktif güç</label><div class="power"><span>—</span><em>kW</em></div><div class="bar"><i></i></div><label>Günlük üretim</label><div class="energy"><span>—</span><em>kWh</em></div><button>Detayları gör ↗</button>`;card.querySelector('button').onclick=()=>openDetail(u);cards.append(card)}
function showDetails(){if(!current||selected==null)return;const d=current.devices.find(x=>x.unit_id===selected);el('detail-title').textContent=d.name;el('detail-time').textContent=`IEC104 · CA ${current.common_address} · Canlı kalite kontrolü`;const grid=el('detail-grid');grid.replaceChildren();for(const [key,s] of Object.entries(d.signals)){const box=document.createElement('div');box.className='detail';const label=document.createElement('label');label.textContent=s.label;const strong=document.createElement('strong');strong.textContent=key==='status'?(current.sunspec?.states?.[s.value]??'Bilinmiyor'):fmt(s.value,['alarm_code','evt1_hi','evt2_lo','evt2_hi'].includes(key)?0:key==='power_factor'?3:1);const unit=document.createElement('em');unit.textContent=s.unit;const meta=document.createElement('small');meta.textContent=`IOA ${s.ioa} · ${s.quality} · ${s.age_seconds==null?'Henüz alınmadı':s.age_seconds+' sn önce'}`;box.append(label,strong,unit,meta);grid.append(box)}}
function openDetail(unit){selected=unit;showDetails();el('details').showModal()}
el('close').onclick=()=>el('details').close();el('analyzer-details').onclick=()=>openDetail(11);el('details').addEventListener('click',e=>{if(e.target===el('details')){const r=el('details').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)el('details').close()}});
function draw(history){const canvas=el('chart'),r=canvas.getBoundingClientRect(),ratio=devicePixelRatio||1;canvas.width=r.width*ratio;canvas.height=r.height*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);const w=r.width,h=r.height,pad=36;ctx.strokeStyle='#29374a';ctx.fillStyle='#8d9db3';ctx.font='10px system-ui';const max=Math.max(100,...history.map(x=>x.power_kw))*1.12;for(let j=0;j<=3;j++){const y=8+(h-24)*j/3;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w,y);ctx.stroke();ctx.fillText(fmt(max*(1-j/3),0),0,y+4)}if(history.length<2){ctx.fillText(history.length?'Trend için sonraki ölçüm bekleniyor':'IEC104 ölçümleri bekleniyor',pad+20,h/2);return}const t0=new Date(history[0].received_at).getTime(),t1=new Date(history.at(-1).received_at).getTime();ctx.beginPath();let prev=null;for(const pt of history){const t=new Date(pt.received_at).getTime(),x=pad+(w-pad)*(t-t0)/Math.max(1,t1-t0),y=8+(h-24)*(1-pt.power_kw/max);if(prev===null||t-prev>15000)ctx.moveTo(x,y);else ctx.lineTo(x,y);prev=t}ctx.strokeStyle='#a7f474';ctx.lineWidth=2;ctx.stroke();el('chart-start').textContent=new Date(history[0].received_at).toLocaleTimeString('tr-TR')}
function render(data){current=data;renderSolar(data);const a=data.devices.find(x=>x.unit_id===11);const connected=data.connected;el('connection').textContent=connected?'IEC104 bağlı':'IEC104 bağlantısı yok';el('connection').className='badge '+(connected?'good':'bad');el('endpoint').textContent=data.endpoint;el('plant-power').textContent=fmt(value(a,'power_kw'));el('plant-daily').textContent=fmt(value(a,'daily_kwh'));el('plant-total').textContent=fmt(value(a,'total_kwh'));el('plant-pf').textContent=fmt(value(a,'power_factor'),3);el('frequency').textContent=`Frekans: ${fmt(value(a,'frequency'),2)} Hz`;const valid=value(a,'power_kw')!=null;el('analyzer-status').textContent=valid?'Güncel ölçüm':'Veri eksik / eski';el('analyzer-status').className='badge '+(valid?'good':'bad');let count=0;for(let u=1;u<=10;u++){const d=data.devices.find(x=>x.unit_id===u),card=el(`inv-${u}`),p=value(d,'power_kw'),status=value(d,'status');card.querySelector('.power span').textContent=fmt(p);card.querySelector('.energy span').textContent=fmt(value(d,'daily_kwh'));card.querySelector('.state').textContent=p==null?'Veri eksik / eski':(data.sunspec?.states?.[status]??'Durum verisi yok');card.querySelector('.screen').className='screen '+([4,5].includes(status)&&p!=null?'online':'');card.querySelector('.bar i').style.width=`${p==null?0:Math.min(100,100*p/(value(d,'rated_kw')||100))}%`;if([4,5].includes(status)&&p!=null)count++}el('production-count').textContent=`${count} / 10 üretimde`;el('notice').textContent=!connected?'IEC104 bağlantısı yok. Telediagram çıkış IP, port ve CA ayarını kontrol edin.':!valid?'Bağlantı kuruldu; analizör noktaları bekleniyor. IOA, tip ve veri kalitesini kontrol edin.':'Güncel ölçümler alınıyor. Her noktada kalite ve veri yaşı ayrı kontrol edilir.';draw(data.history);if(el('details').open)showDetails()}
function offline(){el('connection').textContent='Veri alıcıya ulaşılamıyor';el('connection').className='badge bad';el('notice').textContent='Arayüzün veri alıcısıyla bağlantısı kesildi.';if(current){const d=structuredClone(current);d.connected=false;if(d.weather)d.weather={...d.weather,usable:false,status:"UNAVAILABLE",current:null};for(const device of d.devices)for(const s of Object.values(device.signals)){s.value=null;s.quality='STALE'}render(d);el('connection').textContent='Veri alıcıya ulaşılamıyor';el('notice').textContent='Arayüzün veri alıcısıyla bağlantısı kesildi.'}}
async function refresh(){try{const response=await fetch('/api/state',{signal:AbortSignal.timeout(4000),cache:'no-store'});if(!response.ok)throw Error(response.status);render(await response.json())}catch(error){offline()}finally{el('clock').textContent=new Date().toLocaleTimeString('tr-TR');setTimeout(refresh,1000)}}
window.addEventListener('resize',()=>draw(current?.history??[]));draw([]);refresh();

// Only IEC104 device events drive observed alarms. Lab commands never synthesize telemetry.
const alarmsSection=document.createElement('section');alarmsSection.className='alarm-panel';
alarmsSection.innerHTML='<div class="section-title"><h2>Alarm merkezi</h2><span id="alarm-count" class="badge">Veri bekleniyor</span></div><p class="muted">Onaylama alarmı kapatmaz. Normalleşme IEC104 ile gelen cihaz olay bitlerinden alınır. Haberleşme kaybında son alarm durumu korunur.</p><div id="active-alarms"></div><h3>Kalıcı alarm geçmişi</h3><button id="load-older">Daha eski kayıtları getir</button><div class="alarm-scroll"><table><thead><tr><th>Cihaz / alarm</th><th>Başlangıç</th><th>Normalleşme</th><th>Onay</th><th>İşlem</th></tr></thead><tbody id="alarm-history"></tbody></table></div>';
el('notice').before(alarmsSection);
let alarmRows=[],historyBefore=null,historyBusy=false;
const ts=v=>v?new Date(v).toLocaleString('tr-TR'):'—';
function alarmCardState(data){
 const all=data.alarms??[];renderTestPanel(data);
 for(let u=1;u<=10;u++){
  const card=el(`inv-${u}`),rows=all.filter(a=>a.unit_id===u),active=rows.filter(a=>a.active===true),unknown=rows.filter(a=>a.active===null&&a.last_known_active);
  card.classList.toggle('alarm-active',active.length>0);card.classList.toggle('alarm-unknown',unknown.length>0&&!active.length);
  if(active.length)card.querySelector('.state').textContent=`● ALARM · ${active.length} aktif`;
  else if(unknown.length)card.querySelector('.state').textContent='Son alarm aktif · veri doğrulanamıyor';
  let tag=card.querySelector('.alarm-label');if(!tag){tag=document.createElement('small');tag.className='alarm-label';card.querySelector('button').before(tag)}
  tag.textContent=active.map(a=>a.label).join(' · ');
 }
 const visible=all.filter(a=>a.active===true||(a.active===null&&a.last_known_active));
 el('alarm-count').textContent=`${all.filter(a=>a.active===true).length} aktif · ${all.filter(a=>a.active!==null).length}/${all.length} doğrulandı · ${all.filter(a=>a.active===null&&a.last_known_active).length} son durumu aktif`;
 const host=el('active-alarms');host.replaceChildren();
 if(!visible.length){const p=document.createElement('p');p.className='muted';p.textContent='Güncel aktif cihaz olayı yok. Evt1 parçaları alınmayan cihazların alarm durumu bilinmiyor.';host.append(p)}
 for(const a of visible){const box=document.createElement('div');box.className='alarm-row '+(a.active===true?'red':'amber');
  const text=document.createElement('span');text.textContent=`İnvertör ${String(a.unit_id).padStart(2,'0')} · ${a.label} · Evt1 bit ${a.bit} · IOA ${a.signal_ioa} · ${a.state} · ${a.quality}`;box.append(text);
  if(a.occurrence&&!a.occurrence.acknowledged_at)box.append(ackButton(a.occurrence.id));
  host.append(box);
 }

}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.detail??'İşlem başarısız');return data}
function ackButton(id){const b=document.createElement('button');b.textContent='Onayla';b.onclick=async()=>{const name=prompt('Operatör adı (yerel kayıt; doğrulanmış kimlik değildir):',localStorage.getItem('alarm-operator')??'');if(!name?.trim())return;try{await post(`/api/alarms/${id}/ack`,{operator:name.trim()});localStorage.setItem('alarm-operator',name.trim());await updateAlarmHistory(true)}catch(e){alert(e.message)}};return b}
function renderAlarmHistory(){const host=el('alarm-history');host.replaceChildren();for(const a of alarmRows){const tr=document.createElement('tr');for(const v of [`İnvertör ${a.unit_id} · ${a.label}${a.initial_observation?' (ilk gözlemde aktif)':''}`,ts(a.raised_at),ts(a.cleared_at),a.acknowledged_at?`${a.acknowledged_by} · ${ts(a.acknowledged_at)}`:'Onaylanmadı']){const td=document.createElement('td');td.textContent=v;tr.append(td)}const td=document.createElement('td');if(!a.acknowledged_at)td.append(ackButton(a.id));tr.append(td);host.append(tr)}el('load-older').disabled=historyBefore==null}
async function updateAlarmHistory(reset=false){if(historyBusy)return;historyBusy=true;try{const suffix=!reset&&historyBefore?`&before=${historyBefore}`:'';const r=await fetch('/api/alarms/history?limit=100'+suffix);if(!r.ok)throw Error();const d=await r.json();if(reset){const seen=new Map(alarmRows.map(a=>[a.id,a]));for(const a of d.items)seen.set(a.id,a);alarmRows=[...seen.values()].sort((a,b)=>b.id-a.id);if(historyBefore==null&&alarmRows.length<=100)historyBefore=d.next_before;}else{alarmRows=[...alarmRows,...d.items];historyBefore=d.next_before;}renderAlarmHistory()}catch(e){el('alarm-count').textContent='Alarm geçmişine ulaşılamıyor'}finally{historyBusy=false}}
el('load-older').onclick=()=>updateAlarmHistory(false);
const baseRender=render;render=function(data){baseRender(data);alarmCardState(data)};
const baseDetails=showDetails;showDetails=function(){baseDetails();if(!current||selected==null)return;const device=current.devices.find(d=>d.unit_id===selected),low=value(device,'alarm_code'),high=value(device,'evt1_hi');const raw=document.createElement('div');raw.className='detail';const rawLabel=document.createElement('label');rawLabel.textContent='SunSpec Evt1 — birleşik olay maskesi';const rawValue=document.createElement('strong');rawValue.textContent=low==null||high==null?'Bilinmiyor':`${low+high*65536} · 0x${(low+high*65536).toString(16).padStart(8,'0')}`;raw.append(rawLabel,rawValue);el('detail-grid').prepend(raw);for(const a of (current.alarms??[]).filter(a=>a.unit_id===selected)){if(a.active===null&&!a.last_known_active)continue;const box=document.createElement('div');box.className='detail '+(a.active===true?'alarm-active':'');const label=document.createElement('label');label.textContent=a.label;const strong=document.createElement('strong');strong.textContent=a.active===null?'Bilinmiyor':a.active?'AKTİF':'Normal';const small=document.createElement('small');small.textContent=`RTU · Evt1 bit ${a.bit} · IOA ${a.signal_ioa} · ${a.quality}`;box.append(label,strong,small);el('detail-grid').append(box)}};
const baseOffline=offline;offline=function(){if(current){for(const a of current.alarms??[]){a.last_known_active=a.last_known_active||a.active===true;a.active=null;a.quality='STALE';a.state='UNKNOWN'}}baseOffline()};
updateAlarmHistory(true);setInterval(()=>{if(document.visibilityState==='visible')updateAlarmHistory(true)},5000);

const testPanel=document.createElement('section');testPanel.className='alarm-panel test-panel';
testPanel.innerHTML='<div class="section-title"><h2>Laboratuvar · Manuel cihaz arızası</h2><span class="badge">Yalnızca simülatör</span></div><p class="muted">Bu kontroller cihaz olayını simülatörde oluşturur. Güç, durum ve alarmın gerçekleşmesi Modbus → Telediagram → IEC104 üzerinden doğrulanır. SunSpec olayları birden fazla seçilebilir; bu sayılar hata sıra numarası değildir.</p><div class="test-controls"><label>İnvertör<select id="test-unit"></select></label><label>Cihaz olayı<select id="test-event"></select></label><label>Operatör<input id="test-operator" maxlength="80" placeholder="Adınız"></label><button id="test-raise">Olayı oluştur</button><button id="test-clear-event">Seçili olayı temizle</button><button id="test-clear-all">Bu invertörün testlerini temizle</button></div><p id="test-status" role="status" aria-live="polite">Test istekleri cihaz ölçümü değildir.</p><p id="test-observation" class="muted"></p>';
alarmsSection.before(testPanel);
for(let u=1;u<=10;u++){const option=document.createElement('option');option.value=u;option.textContent=`İnvertör ${String(u).padStart(2,'0')}`;el('test-unit').append(option)}
el('test-operator').value=localStorage.getItem('alarm-operator')??'';
let testLoaded=false,testBusy=false;
function renderTestPanel(data){
 testPanel.hidden=!data.simulation?.enabled;
 if(!testLoaded&&data.sunspec?.events){for(const e of data.sunspec.events){const o=document.createElement('option');o.value=e.bit;o.textContent=`${e.label} · bit ${e.bit} · ${e.reaction}`;el('test-event').append(o)}testLoaded=true}
 const unit=Number(el('test-unit').value),bits=data.simulation?.units?.[unit]?.bits??[];
 const requested=bits.map(bit=>data.sunspec.events.find(e=>e.bit===bit)?.label??bit);
 const d=data.devices.find(x=>x.unit_id===unit),lo=value(d,'alarm_code'),hi=value(d,'evt1_hi');
 const mask=lo==null||hi==null?null:lo+hi*65536;
 el('test-observation').textContent=`İstenen testler: ${requested.join(', ')||'Yok'} · IEC104 St: ${data.sunspec?.states?.[value(d,'status')]??'Bilinmiyor'} · IEC104 Evt1: ${mask==null?'Bilinmiyor':'0x'+mask.toString(16).padStart(8,'0')}`;
}
async function testAction(kind){
 if(testBusy)return;
 const operator=el('test-operator').value.trim();if(!operator){el('test-status').textContent='Operatör adını yaz.';return}
 const unit=Number(el('test-unit').value),bit=Number(el('test-event').value);
 testBusy=true;for(const id of ['test-raise','test-clear-event','test-clear-all'])el(id).disabled=true;
 try{await post(`/api/simulation/${unit}/${kind==='all'?'clear':'event'}`,kind==='all'?{operator}:{operator,bit,active:kind==='raise'});localStorage.setItem('alarm-operator',operator);el('test-status').textContent='İstek kaydedildi. Cihaz alarmı ve ölçümleri için IEC104 dönüşü bekleniyor.'}
 catch(e){el('test-status').textContent=e.message}
 finally{testBusy=false;for(const id of ['test-raise','test-clear-event','test-clear-all'])el(id).disabled=false}
}
el('test-raise').onclick=()=>testAction('raise');el('test-clear-event').onclick=()=>testAction('clear');el('test-clear-all').onclick=()=>testAction('all');
el('test-unit').onchange=()=>{if(current)renderTestPanel(current)};

function renderSolar(data){
 const rows=data.devices.filter(d=>d.unit_id<=10).map(d=>d.signals.irradiance).filter(s=>s&&s.quality==='GOOD'&&typeof s.value==='number'&&Number.isFinite(s.value)&&s.value>=0&&data.connected);
 const average=rows.length?rows.reduce((sum,s)=>sum+s.value,0)/rows.length:null;
 el('solar-irradiance').textContent=fmt(average,0);
 el('solar-mini-state').textContent=rows.length===10?'IEC104':rows.length?'Kısmi veri':'Veri yok';
 el('solar-mini').classList.toggle('solar-unavailable',!rows.length);
 el('solar-mini').title=`İnvertör panel düzlemi ışınımı · IEC104 · ${rows.length}/10 cihazın geçerli verisinin ortalaması. Hava modeli girdisi, simülatör üzerinden cihaz ölçümüne dönüşür.`;renderWeather(data.weather);
}

function renderWeather(w){
 const host=el('weather-mini');host.hidden=!w||w.status==='DISABLED';if(!w)return;
 const c=w.usable?w.current:null,code=c?.weather_code;
 el('weather-location').textContent='Gölbaşı';
 el('weather-temperature').textContent=c?`${fmt(c.temperature_2m,1)} °C`:'— °C';
 el('weather-status').textContent=w.status==='FRESH'?'':w.status==='CACHED'?'Önbellek':w.status==='STALE'?'Eski veri':'Hava yok';
 el('weather-icon').textContent=!c?'—':code===0?(c.is_day?'☀':'☾'):code<=2?(c.is_day?'🌤':'☁'):code===3?'☁':[45,48].includes(code)?'🌫':code>=95?'⛈':([71,73,75,77,85,86].includes(code)?'❄':'🌧');
 host.title=`${w.location} · ${w.description} · Open-Meteo hava modeli (istasyon ölçümü değil) · ${w.status} · Veri zamanı: ${w.weather_time?ts(w.weather_time):'Yok'} · Kaynak yaşı: ${w.age_seconds??'—'} sn`;
}
