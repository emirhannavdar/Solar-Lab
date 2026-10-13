# Solar Lab — 10 invertör + analizör

Çalışma akışı:

**simulator.py → Modbus TCP → Mikrodev RTU (Telediagram projesi) → IEC104 → receiver.py → tarayıcı**

Arayüz doğrudan simülatöre bağlanmaz. `receiver.py` yalnızca IEC104 alır; Modbus okuma veya sahte veriye dönüş yoktur.

## 1. Windows kurulumu

Bu paket Python **3.12 / 64 bit** ile test edildi. IEC104 için kullanılan c104 2.2.1'in Python 3.12 Windows paketi bulunur. Python 3.14 ortamından ayrı bir sanal ortam kullanın.

ZIP'i çıkarın, `solar_lab` klasöründe PowerShell açın:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Birinci terminal — simülatör:

```powershell
.\.venv\Scripts\python.exe simulator.py
```

İkinci terminal — IEC104 alıcı ve arayüz:

```powershell
.\.venv\Scripts\python.exe receiver.py
```

Tarayıcı: http://127.0.0.1:8000

`start_simulator.bat` ve `start_ui.bat` aynı işlemleri yapar. Önce sanal ortamı kurun. Telediagram dönüşümü hazırlanmadan ölçümlerin boş görünmesi beklenen davranıştır.

## 2. Bağlantı ayarları

| Bileşen | Ayar |
|---|---|
| Simülatör | Bilgisayarın LAN IP adresi, TCP 5020 |
| İnvertörler | Unit ID 1–10 |
| Analizör | Unit ID 11 |
| Modbus okuma | FC03, PDU başlangıç 0, 50 adet 16 bit register |
| Her sinyal | FLOAT32, iki register, ABCD / big endian; yüksek word önce |
| IEC104 çıkışı | RTU LAN IP adresi, TCP 2404 |
| IEC104 Common Address / ASDU | 1 |
| IEC104 ölçüm tipi | M_ME_NC_1, Type ID 13 |
| Ölçek | 1; güç kW, enerji kWh olarak hazır |
| Okuma / gönderim | Yaklaşık 1 saniye |

`0.0.0.0` yalnızca simülatörün dinleme adresidir. RTU'ya hedef IP olarak **bilgisayarın gerçek LAN IP adresini** yazın. RTU ve bilgisayar aynı erişilebilir ağda olmalı. Windows güvenlik duvarında RTU'nun TCP 5020 erişimine izin verin.

`config.json` içindeki `iec_host` değerini **RTU IP adresiyle** değiştirin ve `receiver.py` uygulamasını yeniden başlatın. `127.0.0.1` sadece yerel TEST gateway kullanıldığında uygundur.

## 3. Telediagram'da önce iki ölçümle doğrulama

Telediagram RTU projesini düzenler; IEC104 sunucusu RTU üzerinde çalışır. Yerel PC simülatöründen Modbus okuyacak TCP istemci/Modbus master bağlantısını oluşturun. Editör/firmware sürümüne göre Modbus bloklarının isimleri değişebildiği için ekranınızı gördükten sonra blokları birlikte eşleştireceğiz.

İlk aşamada Unit ID 1 için:

| Ölçüm | PDU adresi | Register | Tür | IEC104 IOA |
|---|---:|---:|---|---:|
| Aktif güç | 0 | 2 | FLOAT32 ABCD | 1001 |
| Günlük üretim | 2 | 2 | FLOAT32 ABCD | 1002 |

Adres alanı PDU / sıfır tabanlı ise 0 ve 2 girin. Klasik 4xxxx gösterimi kullanıyorsa karşılıkları 40001 ve 40003'tür. **PDU alanına 40001 yazmayın.** Register sayısı 16 bit word sayısıdır; FLOAT32 için iki word gerekir. UINT32 seçmeyin; float bitlerini tamsayı gibi okumak yanlış değer üretir. FLOAT32 doğrudan desteklenmiyorsa iki word'ü doğru sırada IEEE754 FLOAT32'ye dönüştürüp IEC104 nesnesine bağlayın.

IEC104 bağlantısı için:

1. `TCP Soket` bloğunu **Sunucu**, port **2404** olarak ayarlayın.
2. Soketin `Etk` girişini `Yüksek Kapısı` ile etkinleştirin.
3. `IEC104 Köle` bloğunun `Ser` girişine bu TCP soketi bağlayın.
4. ASDU / Common Address değerini **1** ayarlayın. Tek set için `Object Sets = 1`; değişken tablosunda `Object Set No = 0`.
5. Güç ve günlük enerji değerlerine `INV01_POWER_KW`, `INV01_DAILY_KWH` gibi hat etiketleri verin.
6. Değişken adres tablosunda protokol **IEC104**, nesne tipi **M_ME_NC_1 / 13**, adresleri **1001** ve **1002** yapın; ilgili hat etiketlerine bağlayın.
7. Periyodik gönderimi etkinleştirip köle bloğunun tetik girişine yaklaşık 1 saniyelik yükselen kenar üretin. GI sorgularını da yanıtlayın; alıcı bağlanınca ve her 10 saniyede GI gönderir.
8. Modbus haberleşmesi kaybolduğunda IEC104 kalite bilgisini Invalid / NonTopical olarak taşıyın. Aksi halde RTU eski değeri GOOD olarak tekrar gönderirse alıcı bunun kaynağının eski olduğunu anlayamaz.
9. Projeyi RTU'ya yükleyin, online izlemeyle Modbus değerini doğrulayın. Sonra `receiver.py` ile bağlanın.

IEC104 RTU yapılandırma kaynağı: https://docs.mikrodev.com/tr/docs/Telediagram-Editor/

## 4. Tüm ölçümlere genişletme

İlk iki nokta doğrulandıktan sonra aynı bağlantı için Unit ID 2–10 ve analizör Unit ID 11'i ekleyin. Her cihazın ayrı Unit ID'si vardır; tek portta adres bankaları bağımsızdır.

`point_map.csv` dosyasında **269 noktanın** tüm adresleri ve türleri bulunur. Bu CSV bir eşleştirme rehberidir; Telediagram'a doğrudan proje dosyası olarak yüklenmez. Editörün içe aktarma formatına uyarlamak için sürüm ve örnek dışa aktarma dosyası gerekir.

IOA kuralı: `Unit ID × 1000 + sinyal sırası` (sıra 1'den başlar).

Örnek: ikinci invertör güç 2001; onuncu invertör güç 10001; analizör güç 11001 ve günlük enerji 11002. Aynı Modbus PDU adresi farklı Unit ID'lerde farklı cihaz ölçümüdür; IEC104 IOA'ları ise birbirinden farklıdır.

Zaman etiketli ölçüm gerekiyorsa `config.json` içindeki `iec_type` değerini `M_ME_TF_1` yapın, Telediagram noktalarını Type ID 36 seçin ve `python export_map.py` ile listeyi yenileyin. Tip 13 kullanıldığında kaynak zamanı yoktur; arayüz veri alım zamanını takip eder.

## 5. Simülasyon modeli

Varsayılan: **10 × 100 kW**, toplam **1 MW** AC nominal güç. `inverter_rated_kw` ve `dc_ac_ratio` değiştirilebilir. Bu, belirli bir üreticinin register profili değil, genel üç fazlı güneş invertörü modelidir.

- Ortak ışınım ve yumuşak bulut değişimi; her invertörde küçük panel gölgeleme farkı.
- DC güç, ışınım / panel sıcaklığı / DC kapasitesinden; AC güç, DC güç ve yükle değişen verimden hesaplanır. Nominal güçte MPPT sınırlaması yapılır.
- Reaktif ve görünür güç, güç faktöründen hesaplanır. Üç faz akımları gerilim ve görünür güçle tutarlıdır. DC akımı DC güç / DC gerilim ilişkisinden türetilir.
- İç sıcaklık güç ve ortam sıcaklığına gecikmeli yaklaşır.
- Günlük enerji rastgele üretilmez: güç zaman üzerinden trapez yöntemiyle entegre edilir. Gece güç ve enerji artışı sıfırdır; gece yarısında günlük sayaç sıfırlanır.
- Yeni kurulumda, başlangıç saatine kadar olan aynı günün üretimi modelden hesaplanır; öğlen sıfır günlük üretimle başlamaz. Toplam sayaçların başlangıç değerleri örnek cihaz geçmişidir.
- Analizör aynı anlık modelden aktif/reaktif güç, enerji ve faz akımlarını toplar. Gerilim/frekans ortak şebeke değerleridir. Analizörde invertör DC bilgileri / verim / soğutucu sıcaklığı noktaları bulunmaz.
- Ölçümler yalnızca okunabilir; Modbus yazma komutları desteklenmez.

`mode: demo` varsayılan olarak yaz günü 11:00'den başlar, `time_scale: 1` gerçek süreyle ilerler. `time_scale: 60` yaparsanız her gerçek saniye bir simülasyon dakikası olur; enerji aynı oranda doğru entegre edilir. `mode: realtime` gerçek yerel saatle başlar. Sabit 06:00–20:00 güneş penceresi temsili yaz günü içindir; mevsim/konum hesabı yoktur.

`faulted_units: [4]` dördüncü invertörü arızalı yapar; güç sıfır, durum 2, alarm 1 olur. Ayarlar başlangıçta okunur; değişiklikten sonra simülatörü yeniden başlatın.

`state.json` sayaçları 10 saniyede bir ve Ctrl+C ile kapanışta saklar. Demo yeniden başlatıldığında kayıtlı simülasyon saatinden devam eder. Yeni senaryo başlatmak için simülatörü durdurup state.json dosyasını silin. Program kapalıyken geçen süre için enerji hesaplanmaz; ani süreç sonlandırmada son kontrol noktasından sonraki birkaç saniye kaybolabilir.

## 6. Arayüz ve veri kalitesi

Üstte analizör güç, günlük/toplam enerji, güç faktörü ve güç trendi; altta 10 invertörün güç/günlük enerji kartları vardır. Detay düğmeleri cihazın diğer ölçümlerini ve IOA/kalite/veri yaşını açar. Geniş ekranda 10 kart yan yanadır; dar ekranda satırlara bölünür.

Bağlantı yoksa, kalite kötüyse veya ölçüm 15 saniyeden eskiyse güncel değer boş gösterilir. Veriler ve son 30 dakika trendi alıcı belleğindedir; alıcı yeniden başlayınca temizlenir. Bu sürüm kalıcı ölçüm arşivi içermez. Noktalar IEC104 ile ayrı mesajlarda gelebilir; çok küçük anlık toplam farkları mesaj zamanlarından kaynaklanabilir.

## 7. Telediagram olmadan entegrasyon testi

Gerçek kullanımda **test_gateway.py çalıştırmayın**. Bu dosya sadece Telediagram yerine test dönüştürücüsüdür. RTU portuyla karıştırmayın.

Otomatik doğrulama (önce elle başlattığınız simülatör/alıcı/test gateway'i kapatın; 5020/2404/8000 boş olsun):

```powershell
.\.venv\Scripts\python.exe test_system.py
.\.venv\Scripts\python.exe verify_chain.py
```

İkinci komut test süreci boyunca simülatör, test IEC104 sunucusu ve alıcıyı başlatır; 269 noktayı ve bağlantı kopmalarını doğrular, sonra kapatır. Fizik testleri toplam, elektrik ilişkileri, enerji integrali, gece, arıza, gece yarısı, sayaç kalıcılığı, FLOAT32 sırası ve Modbus hata yanıtlarını kapsar.

Yerel arayüzü test dönüştürücüsüyle görmek için üç ayrı terminalde `simulator.py`, `test_gateway.py`, `receiver.py` çalıştırın; `iec_host` bu senaryoda 127.0.0.1 olmalıdır.
