# Current Handoff

Bu dosya, Fisora kapali server demo calismasina baska bilgisayardan veya baska
oturumdan devam etmek icin son durumu ozetler.

## Son Durum

- Repo: `keremerdogdu92/Fisora`
- Aktif branch: `main`
- Son dogrulanan runtime kod release'i: `9770e70`; kod release scripti
  `before_commit=3602c7c`, `after_commit=9770e70`, `smoke=ok`, `/health`
  200, readiness 200, root route 200, `ready=true`, `pilot_sellable=true`
  dondu.
- Son deploy smoke: 2026-07-03, `/health` 200, readiness `ready=true`,
  `pilot_sellable=true`; root route 200.
- KDV ayrimi guven katmani canlida: PDF faturalarda `exact`, `derived`,
  `needs_review` statuleri uretildi; belge isleme sonucuna `vat_split_review`
  kaydi, pipeline'a `vat_split_classified`, musavir onayina
  `vat_split_review_saved` olayi eklendi.
- 2026-06-29 hesap plani ve AI karar kapisi release'i canliya alindi:
  kesin KDV/hukuki kurallar AI tarafindan ezilmez. Bu release'te AI yalniz
  belirsiz satir, zayif hesap adayi veya marka/model-only aciklamalarda
  devreye giriyordu; 2026-07-02 yururluk notuyla bu kapi AI-first soguk
  baslangic yorumlayicisi olacak sekilde genisletildi.
- 2026-07-02 yururluk notu: yeni AI-first karar motoru hedefinde AI soguk
  baslangicta ana fatura anlamlandirici katmandir. Deterministik motor KDV,
  borc/alacak dengesi, mevcut hesap plani aday listesi, kesin kanuni kurallar
  ve export kapisini korur. AI mevcut hesap plani adayindan hesap sectiyse
  motor bunu hesap ailesi filtresiyle daha genel bir hesaba kaydirmaz; yanlis
  muhasebe yorumu mustavir review/learning dongusunde duzeltilir. Tavily
  yalniz AI emin degilse, urun yeni/belirsizse veya faaliyet/NACE baglami
  eksikse calisir. Musavir onay/duzeltmeleri learning event olarak AI/research
  tekrarini azaltacak sekilde kullanilir.
- 2026-07-02 canli uygulama durumu: cold-start core business stok/COGS satiri
  `cold_start_core_accounting_line` gerekcesiyle kabul ediliyor; AI
  `needs_research=true` dediginde kategori bilinse veya guven yuksek olsa bile
  research calisiyor; portal karar zinciri urun kimligi, NACE/faaliyet,
  research ihtiyaci/sorgusu ve cari aday izini gosteriyor. Faz 8 icin cok
  mukellefli private sample matrix ve canli smoke henuz siradaki is.
- 2026-07-03 plan guncellemesi: sabit `12` hesap adayi kirpmasi yerine
  zengin ama olculu iki asamali AI hesap/cari secimi hedeflendi. Aday seti
  kucukse tek cagri kalir; buyukse Stage 1 hesap ailelerini, Stage 2 dar
  gercek hesap listesi ve ilgili `120/320` cari adaylarini secer. Her asama
  `candidate_count`, `input_chars`, secilen aile/hesap/cari ve fallback
  sebebiyle telemetry'ye yazilacak.
- 2026-07-02 belge onizleme duzeltmesi canlida: `/portal/belgeler` orijinal
  belge fetch'i artik diger backend cagrilariyla ayni API base resolver'i
  uzerinden `/api/phase0/store/document-file/...` yoluna gider. Orhan Elibol
  belgesi `1061386125_AVQ2026000000026.pdf` icin canli public API `200
  application/pdf` dondu. Fis toplamlari icin `3399.99` gibi nokta-decimal
  degerler artik `339999.00` olarak sismiyor.
- Muhasebe fisi UX'i guncellendi: `/portal/belgeler` ekraninda fis satirlari
  en onde duzenlenir; `Karar ve gerekce` sureci fisin altinda ikincil alanda
  kalir. `Duzeltme notu` ve `Kural talimati`, fis satiri/hesap-cari
  duzeltmesiyle ayni review payload'inda kaydedilir.
- UI/UX remediation deploy: 2026-06-26, `main` ucu `86000c7`.
  Release orchestrator `smoke=ok`, `/health` 200, readiness `ready=true`,
  `pilot_sellable=true` dondu.
- Canli UI smoke: `http://185.184.208.188/portal/belgeler`,
  `/portal/mukellefler`, `/portal/bilgi-havuzu` dolu render oldu; Next error
  overlay yok, console error/warn yok, desktop overflow `0px`.
  `/portal/mukellefler` yeni onboarding adimlari ve blocked-reason metniyle
  render oldu; `Yardim` topbar dialog'u canlida acildi.
- Belge isleme sayfasinda temkinli `Belge ajani` ve `Arastirma ajani`
  kapasite gostergesi canlida dogrulandi. Tavily usage snapshot'i 10 dakika
  cache edilir; hesap iki deneme ve yuzde 25 operasyon rezervi kullanir.
- Musavir dashboard metrikleri kompakt ikonlu kartlara tasindi; desktop 6
  sutun, tablet 3x2, mobil 2x3 duzeni ve sol menu ikonlari canlida
  dogrulanacak runtime kapsamindadir.
- Belge isleme ekrani altta genis belge listesi, ustte belge onizleme ve
  muhasebe fisi olacak sekilde yenilendi. Teknik pipeline varsayilan kapali,
  sol menu daraltilabilir; canli `/portal/belgeler` rotasinda dogrulandi.
- Server repo dizini: `/opt/fisora/app`
- Server runtime: Docker Compose production stack
- Demo provider: Groq
- AI fallback kodu: `FISORA_AI_PROVIDER_CHAIN=groq,openrouter,cerebras`
  destekli. Keyler sadece serverdaki ignored `deploy/production.env` dosyasinda
  tutulur.
- Faz 3 Tavily Bilgi Havuzu pilot akisi hazirlandi. Otomatik research sadece
  belirsiz faturalarda calisir; OpenAI web research sonraki iterasyon icin
  kodda korunur. Tavily icin `FISORA_RESEARCH_ENABLED=true`,
  `FISORA_RESEARCH_PROVIDER=tavily` ve `TAVILY_API_KEY` gerekir. Bilgi Havuzu
  route'u: `/portal/bilgi-havuzu`.
- Server env dosyasi: `/opt/fisora/app/deploy/production.env`

`deploy/production.env` GitHub'a girmez. `POSTGRES_PASSWORD`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY`, `CEREBRAS_API_KEY` ve varsa fallback provider keyleri
sadece serverdaki bu dosyada tutulur.

## 2026-07-08 QNB e-Belge Entegrasyon Karari

QNB eSolutions test ortami basvurusu sonucunda Fisora, SaaS/ERP entegrasyonu
olarak kabul edildi ve Fisora'ya ERP kodu tanimlandi. ERP kodu QNB SOAP
parametrelerinde kullanilacak sabit uygulama kodudur; tum firmalarda ayni
kalir. Tam kod, test kullanici sifreleri ve canli kimlik bilgileri repoya
yazilmaz; mail/secret kaynagindan alinarak ignored env icinde tutulmalidir.

QNB tarafindan bildirilen teknik durum:

- Rate limit: dakikada 180 request.
- e-Fatura ve e-Irsaliye testleri `erpefaturatest1` ve `erpefaturatest2`
  ortamlarinda yapilacak. Bu iki ortam karsilikli belge gonderip alabilecek
  sekilde tanimli; ayni ortamdan ayni ortama belge gonderimi testte yok.
- e-Arsiv, e-Defter, eSMM, eMM, e-Adisyon ve e-SKGB testleri
  `portaltest` / `connectortest` / `earsivtest` ortamlarinda yapilacak.
- Canli ortamda tek kullanici adi/sifre ile butun servislere erisilebilecegi
  bildirildi; testte ortamlar ayridir.
- QNB, portal kullanicisi ile web servis kullanicisinin ayrilmasini onerdi.
  Portal sifresi degisimleri WS login tarafini bloke edebilecegi icin Fisora
  entegrasyonunda ayri WS kullanicisi olusturulmalidir.
- `Ext` ile biten metotlarda ERP kodu dogrudan `erpkodu` parametresiyle
  gonderilmeli; Ext olmayan metotlarda `erpBilgileriBelirle` akisi gerekiyor.
  SOAP header kullanan entegrasyonda Ext metotlari tercih edilmelidir.

Bu karar urun yonunu degistirdi: ana belge girisi artik "mukellef dosya
yuklesin" degil, "QNB'den otomatik belge senkronizasyonu" olmalidir. Manuel
upload sistemi cope gitmez; QNB disi entegratorler, eski belgeler, banka
ekstreleri, vergi levhasi, sozlesme, dekont ve API kesintisi durumlari icin
yedek/manual kaynak adaptoru olarak kalir.

Yeni hedef akisi:

```text
QNB baglantisi/yetkisi -> belge senkronizasyonu -> UBL/PDF/status alma
-> canonical invoice -> iptal/red/itiraz kaniti -> muhasebe fisi taslagi
-> musavir kontrolu -> export
```

Belge saklama politikasi yeniden tasarlanacak. QNB kaynakli belgelerde QNB
yeniden indirme kaynagi olabilir, fakat Fisora yine minimum kanit tutmalidir:

- QNB belge kimligi: ETTN/UUID, belge no, VKN/TCKN, tarih.
- Kaynak ve cekilme zamani.
- UBL/PDF hash'i ve islenen canonical veri.
- Muhasebe fisi taslagi, review kararlari ve export sonucu.
- Iptal/red/itiraz/status kaniti ve son sorgulama zamani.
- Pilot icin UBL/PDF cache tutulmasi onerilir; uzun vadede saklama politikasi
  musteri/mevzuat ihtiyacina gore ayarlanabilir.

QNB entegrasyonu tamamlaninca etkilenecek ana sistemler:

- Onboarding: mukelleften yalniz dosya istemek yerine QNB kullaniyor mu,
  VKN/TCKN, servis kullanicisi/yetki, senkron baslangic tarihi ve musavir
  yetkisi alinacak.
- Mukellef portali: belge yukleyen ana kullanici yerine baglanti/yetki veren,
  eksikleri tamamlayan ve yorum/onay veren role kayar.
- Musavir portali: cok mukellefli belge akisi, QNB baglanti durumu, yeni gelen
  belgeler, iptal/red uyarilari, fis taslaklari ve kontrol kuyrugu ana ekran
  haline gelir.
- Parser: UBL canonical veri birincil kaynak olur; PDF daha cok onizleme ve
  gorsel kanit/fallback icin kullanilir.
- Iptal politikasi: "UBL'de iptal yoksa iptal degildir" denmez. QNB status,
  uygulama yaniti, e-Arsiv iptal/itiraz bilgisi, iptalTarihi ve PDF gorsel
  damga ayri kanit katmani olarak izlenir.
- Storage: manuel document store kalir ama QNB icin source-adapter + metadata +
  evidence snapshot modeli hedeflenir.
- Rate limit/worker: dakikada 180 request siniri icin kuyruk, throttle, retry
  ve idempotent sync zorunludur.
- Cok mustavirli SaaS: Fisora platformu altinda birden fazla musavir ofisi,
  her musavirin altinda birden fazla mukellef ve her mukellef icin ayri QNB
  yetki/credential modeli hedeflenir.

Urun modulu kapsami:

- e-Fatura: ilk oncelik. Gelen/giden listeleme, UBL/PDF indirme, durum
  sorgulama, ticari faturada kabul/red uygulama yaniti, ileride Fisora'dan
  fatura kesme.
- e-Arsiv: ilk oncelik. e-Fatura mukellefi olmayanlara/son tuketiciye kesilen
  faturalar; UBL/PDF alma, sorgulama, iptal/itiraz/status kaniti ayrica test
  edilecek.
- e-Irsaliye: e-Fatura ile benzer altyapi ama sevkiyat belgesi. Fatura
  temelinden sonra daha hizli eklenebilir; alanlari ve is kurallari farklidir.
- e-Defter: fatura kesme degil, yasal defter/berat/donem kapanisi sureci.
  QNB donusunde testte CSV format hazirlayip portal upload ile deneme
  anlatildi. Fisora icin ileride e-Defter export/donem hazirligi olabilir.
- eSMM/eMM: muhasebe fisi degil, serbest meslek makbuzu ve mustahsil makbuzu
  gibi fatura benzeri resmi belge tipleri. Kesildikten sonra muhasebe fisine
  kaynak olabilir.
- e-Adisyon/e-SKGB: restoran/adisyon ve sigorta komisyon gider belgesi gibi
  nis alanlar; simdilik ana oncelik degil.

Bir sonraki planlama icin acik kararlar:

1. QNB'den cekilen UBL/PDF dosyalari pilotta kalici mi saklanacak, yoksa
   hash + canonical veri + yeniden indirme modeli mi uygulanacak?
2. Ilk entegrasyon yalniz belge okuma/status mu olacak, yoksa ayni fazda
   fatura kesme/gonderme de kapsama alinacak mi?
3. Cok mustavirli modelde credential sahipligi musavir ofisi bazinda mi,
   mukellef bazinda mi, yoksa ikisi birlikte mi tutulacak?
4. Manuel upload UI ana aksiyon olmaktan cikarilip "manuel/yedek kaynak" olarak
   yeniden konumlandirilacak mi?
5. QNB disi entegratorler icin simdiden generic `document_source_adapter`
   arayuzu tasarlanacak mi?

Pratik siradaki is: QNB entegrasyonu icin tasarim/spec yaz. Once mevcut
document upload pipeline'i kaynak-adaptorlu hale getiren mimariyi netlestir,
sonra kucuk bir proof hedefi sec: SOAP login + e-Fatura/e-Arsiv listeleme veya
belge indirme + status kaniti.

## Yeni Bilgisayarda Devam Etme

GitHub hesabi private repoya yetkili olmalidir. Aktif pilot branch'ini almak icin:

```bash
git clone -b main https://github.com/keremerdogdu92/Fisora.git
cd Fisora
```

Zaten clone varsa:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

## Serverda Kaldigimiz Yer

Serverda Docker kuruldu ve stack bir kez basariyla ayaga kalkti. Su servisler
healthy gorundu:

- `backend`
- `frontend`
- `postgres`
- `redis`
- `nginx`

Nginx `80` portunu disari aciyor. Tarayicida demo URL formati:

```text
http://<SERVER_IP>/
```

`<SERVER_IP>` degeri repoya yazilmaz; server panelinden veya mevcut SSH
bilgisinden bakilir.

## Serverda Son Kodu Cekme ve Redeploy

Serverda son commit'i almak icin:

```bash
cd /opt/fisora/app
git fetch origin
git checkout main
git pull --ff-only origin main
```

Config kontrolu ve deploy:

```bash
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1 -Branch main -BaseUrl http://185.184.208.188 -SkipLocalVerify -Json
```

## Env Kontrolu

Serverdaki asil env dosyasi:

```bash
nano /opt/fisora/app/deploy/production.env
```

Minimum beklenen satirlar:

```env
POSTGRES_PASSWORD=<strong-password>
FISORA_HTTP_PORT=80
FISORA_AUTH_MODE=mock_header_required
FISORA_AUTH_PASSWORD_BOOTSTRAP_ENABLED=false
FISORA_AI_PROVIDER=groq
FISORA_AI_PROVIDER_CHAIN=groq,openrouter,cerebras
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_GROQ_MODEL=openai/gpt-oss-20b
FISORA_OPENROUTER_MODEL=openai/gpt-oss-20b:free
FISORA_OPENROUTER_SITE_URL=http://185.184.208.188
FISORA_OPENROUTER_APP_TITLE=Fisora Operasyon Portal
FISORA_CEREBRAS_MODEL=gpt-oss-120b
FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b
FISORA_AI_MONTHLY_CAP_USD=0.01
FISORA_RESEARCH_ENABLED=true
FISORA_RESEARCH_PROVIDER=tavily
FISORA_RESEARCH_MODEL=gpt-5.4-mini
FISORA_RESEARCH_MAX_PER_DOCUMENT=1
FISORA_RESEARCH_CONFIDENCE_THRESHOLD=70
GROQ_API_KEY=<groq-key>
OPENROUTER_API_KEY=<rotated-openrouter-key>
CEREBRAS_API_KEY=<cerebras-key>
OPENAI_API_KEY=
TAVILY_API_KEY=<tavily-key>
```

Key'i gostermeden kontrol:

```bash
grep -E 'FISORA_AUTH_MODE|FISORA_AI_PROVIDER|FISORA_AI_PROVIDER_CHAIN|FISORA_AI_MODEL|FISORA_(GROQ|OPENROUTER|CEREBRAS)_MODEL|FISORA_AI_COMPARISON_MODEL' deploy/production.env
grep -q '^GROQ_API_KEY=.' deploy/production.env && echo "GROQ key var" || echo "GROQ key eksik"
grep -q '^OPENROUTER_API_KEY=.' deploy/production.env && echo "OpenRouter key var" || echo "OpenRouter key eksik"
grep -q '^CEREBRAS_API_KEY=.' deploy/production.env && echo "Cerebras key var" || echo "Cerebras key eksik"
```

## Beklenen Health ve Readiness

Server icinden:

```bash
curl -i http://127.0.0.1/health
curl -s http://127.0.0.1/api/phase0/store/auth/status
curl -s http://127.0.0.1/api/phase0/store/system/readiness
```

Beklenen kritik degerler:

```text
health: 200 OK
auth_mode: mock_header_required
ready: true
pilot_sellable: true
production_ready: false
ai_provider: groq
ai_model: openai/gpt-oss-20b
ai_groq_key_present: true
zirve_mapping_adapter_available: true
rate_limit_configured: true
```

`zirve_verified_adapter_missing`, `zirve_field_test_pending` ve
`session_required_missing` warning'leri kapali demo modunda normaldir. Zirve
export sahada mustavirle test edilmeden adapter verified sayilmaz; canlı demo
`mock_header_required` modunda kaldigi surece `production_ready=false` kalir.

## Smoke Durumu

`sh deploy/scripts/fisora-prod.sh smoke` bir kez `failed_count=1` verdi. Bu
backend/frontend/nginx'in ayakta olmadigi anlamina gelmiyor; health kontrolleri
basariliydi. Redeploy sonrasi tekrar bak:

```bash
sh deploy/scripts/fisora-prod.sh smoke
```

Yine failed donerse hata detayini al:

```bash
docker compose --env-file deploy/production.env -f docker-compose.production.yml -p fisora exec postgres psql -U fisora -d fisora -c "select payload->>'status' as status, payload->>'error_message' as error_message, payload from workflow_records where record_type='processing_job' order by updated_at desc limit 5;"
```

## Guvenlik Notlari

- Groq key, GitHub token, SSH private key ve server root sifresi chat'e veya
  repoya yazilmaz.
- Server internete acik oldugu anda bot taramalari gelir; nginx logunda
  bilinmeyen 404 istekleri normaldir ama firewall/IP kisiti planlanmalidir.
- Demo kapali IP ile yapilacaksa once SSH ve HTTP erisimi kimlerle paylasilacak
  netlestirilmelidir.

## Kaldigimiz Pratik Sira

1. Serverda `git checkout main && git pull --ff-only origin main` ile son commit'i cek.
2. `sh deploy/scripts/fisora-prod.sh check && sh deploy/scripts/fisora-prod.sh deploy && sh deploy/scripts/fisora-prod.sh smoke` calistir.
3. Auth status `mock_header_required` donuyor mu kontrol et.
4. Readiness icinde `pilot_sellable=true`, `production_ready=false`,
   `zirve_mapping_adapter_available=true`, `rate_limit_configured=true`,
   `ai_groq_key_present=true` ve `ai_provider_configured=true` mi kontrol et.
5. Tarayicida `http://<SERVER_IP>/` ac.
6. Fatura ve banka upload akisini Groq AI acik halde dene.
7. Smoke failed kalirsa yukaridaki SQL komutuyla job error detayini al.
