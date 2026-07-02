# Teknik Mimari Baslangic Karari

## Production Yon

Baslangic production yonu:

```text
Next.js frontend
FastAPI backend
PostgreSQL database
Python worker
Redis queue
S3-compatible object storage
Docker Compose
Nginx
```

Kiralik kendi sunucu modelinde ilk production kurulumu tek makinede baslayabilir:

```text
Nginx
Docker Compose
Next.js frontend
FastAPI backend
PostgreSQL
Redis
worker
local encrypted document volume
nightly external backup
```

Bu modelde ham belgeler veritabanina yazilmaz. Veritabaninda belge metaverisi,
storage path, dosya boyutu, hash, yukleyen kullanici ve isleme durumu tutulur.
Dosyalar sunucudaki ayrilmis volume'da veya S3-compatible object storage'da
saklanir.

Supabase production ana mimari olarak kullanilmayacak. Sadece demo veya hizli
prototip icin opsiyonel tutulabilir.

## Ana Bilesenler

- Auth ve uyelik: serbest kayit yok; kullanicilar mustavir/ofis tarafindan
  acilir ve mukellefe baglanir.
- Mukellef onboarding: mukellef karti, VKN/TCKN, faaliyet/NACE, isyeri adresi,
  Zirve hesap plani ve opsiyonel yevmiye/muavin exportu alir.
- Belge yukleme: fatura, e-fatura XML/PDF, banka ekstresi ve POS ekstresi
  mukellef yetkisine gore yuklenir.
- Upload protokolu: base64 geriye donuk MVP kontrati korunur; production portal
  dosyalari multipart/form-data ile gonderir.
- Processing queue: upload sonrasi belge icin parser secimi ve job durumu
  olusturur; worker sonucu workspace'e yazar.
- Parser katmani: OCR kullanmadan once text PDF, XML, Excel ve CSV parser
  calisir. OCR sadece text cikmayan belgelerde fallback olur.
- Worker parser baglantisi: text PDF ve e-fatura XML fatura sonucunu simulation
  motoruna, CSV/XLSX banka-POS ekstrelerini statement line sonucuna donusturur.
- Statement fis taslagi: GIB, SGK, POS ve banka satirlarindan 102/108/360/361
  gibi hesaplarla dengeli taslak entry payload'i uretilir; riskli satirlar
  review gate'te kalir.
- Product classification: fatura kalemlerindeki marka/model satirlarini urun
  kategorilerine cevirir.
- AI assisted draft adapter: soguk baslangicta mevcut hesap plani ve cari
  adaylari icinden aciklamali fis taslagi ve taslak hesap secimi onerir;
  export karari vermez.
- Business relevance: urun/hizmet kategorisini mukellef faaliyet profili, NACE,
  isyeri adresi, tedarikci ve gecmis kararlarla karsilastirir.
- Rule engine: genel kurallar, mustavir/ofis politikalari ve mukellef ozel
  kurallari birlestirir.
- Journal engine: dengeli fis taslaklari uretir.
- Review console: mustavir taslagi onaylar, duzeltir, reddeder veya export'a
  hazirlar.
- Correction learning: mustavir kararlarini genel ogrenme adayi, mustavir
  politikasi veya mukellef ozel kural olarak saklar.
- Export package: yalnizca export'a uygun kayitlardan Zirve aktarim dosyasi
  uretir.
- Export workspace builder: fatura ve statement sonucundaki dengeli, risksiz
  entry'leri paketler; riskli satirlari `excluded_document_refs` olarak tutar.
- Export download: paketlenen entry'ler universal journal CSV dosyasina yazilir
  ve mustavir ekranindan indirilebilir.
- Correction preview: mustavirin girdigi hesap/cari duzeltmesi karar
  kaydedilmeden once secili fis taslagi satirinda aninda gorunur.
- AI benchmark: dis provider baglanmadan once statik kural ve replay payload
  sonuclarini ayni schema ile karsilastirir.

## Faz 0 Yon

Faz 0'da asil dogrulanacak kisim frontend degil, muhasebe domain katmanidir. Bu
nedenle hesap plani importu, fis uretimi ve export adaylari saf Python
modulleriyle yazilir.

FastAPI sadece domain prototipini API icinden cagirmaya hazir minimum iskeleti
sunar. Next.js proje yonunu sabitler ve review console icin ilk gorunum saglar.

## Veri Modeli Yonleri

PostgreSQL tablolari ilk etapta davranis seviyesinde su varliklari tasimalidir:

- `accountants` / `offices`: mustavir veya ofis ayarlari.
- `clients`: mukellef karti, VKN/TCKN, faaliyet/NACE, isyeri adresleri.
- `users`: sadece atanmis mukellefler icin belge yukleyebilen kullanicilar.
- `chart_accounts`: Zirve hesap plani ve detay hesap bilgisi.
- `counterparties`: 120/320 cari adaylari, VKN/TCKN, unvan ve hesap kodu.
- `documents`: yuklenen belge, kaynak dosya, parse durumu ve mukellef baglantisi.
- `invoice_lines`: ham kalem metni, marka/model adayi, kategori, KDV ve tutar.
- `journal_drafts`: fis taslagi, risk bayraklari, guven skoru ve durum.
- `review_decisions`: mustavir onayi, duzeltmesi, reddi ve gerekcesi.
- `learning_rules`: tekrar eden kararlar, otomasyon adaylari ve kapsam seviyesi.
- `export_packages`: Zirve'ye aktarilacak onayli kayit paketleri.

Ilk PostgreSQL adapter'i, JSON store ile ayni MVP workspace kontratini
`workflow_records` tablosunda tutar. Bu tablo client, chart account snapshot,
uploaded document, processing job, simulation result, review decision, learning
event ve export package payload'larini kaybetmeden production database'e tasir.
Normalized tablolar pilot veriler netlestikce ana yazma modeli haline getirilecek.

## Worker Akisi

```text
belge yuklendi
  -> mukellef yetkisi ve karti dogrula
  -> processing job olustur
  -> text/XML/Excel/CSV parse et
  -> fatura/ekstre alanlarini cikar
  -> gerekiyorsa AI ile marka-model ve urun kategorisi siniflandir
  -> soguk baslangicta AI assisted draft ile hesap/kategori gerekcesi olustur
  -> business relevance ve risk bayraklarini hesapla
  -> karsi cari ve hesap plani eslestir
  -> dengeli fis taslagi uret
  -> export_ready / review_required / blocked durumunu belirle
  -> review console veya export paketine gonder
```

## Otomasyon Politikasi

- Risk bayragi olmayan, dengeli, cari ve hesap eslesmesi net kayitlar export
  adayi olabilir.
- Supheli veya is alani disi belgelerde fis taslagi uretilir ama export'a
  alinmaz.
- Ayni karar en az 3 kez tutarli onaylanirsa otomasyon adayi olur.
- Dogrudan Zirve'ye gonderim, import formati gercek Zirve testinde dogrulanmadan
  uygulanmaz.

## Ayrilabilir Bilesenler

- Backend API
- Worker
- Database
- Object storage
- Frontend
- Queue
- AI classification adapter
- Zirve export adapter

## AI Provider Yon

Kendi sunucuda AI modeli calistirma baslangic kapsamindan cikarildi. AI,
tek basina nihai kayit atan motor degil; soguk baslangicta fatura satiri,
NACE/faaliyet, hesap plani ve cari adaylarini anlamlandiran ana hizlandirici
katman olarak ele alinacak. Deterministik muhasebe motoru tutar, KDV,
borc/alacak dengesi, hesap kodunun mevcut hesap plani adaylarindan gelmesi ve
export kapisini kontrol eder. AI'in mevcut adaylardan sectigi taslak hesap,
hesap ailesi yorumuyla daha genel bir hesaba geri zorlanmaz; yanlis yorum
mustavir review/learning dongusunde duzeltilir.

AI API'ye uygun isler:

- Marka/model satirindan urun kategorisi adayi cikarma.
- Yeni veya zayif gecmisli mukellefte fatura kalemini NACE/faaliyet baglamiyla
  yorumlama.
- Hesap planindaki mevcut hesap adaylarini anlamlandirip siralama.
- Cari adayi, tedarikci niyeti ve stok/gider/satis niyetini gerekcelendirme.
- Belirsiz fatura kalemine kisa uygunluk gerekcesi yazma.
- Tedarikci/aciklama metnini normalize etme.
- Banka aciklamasini genel kategoriye ayirma.
- Research gerekiyorsa arama sorgusunu daraltma ve research sonucunu muhasebe
  etkisine cevirmeye yardim etme.
- Pilot batch benchmark icin provider cevabini kategori/guven/gerekce JSON
  schema'siyla olcmek.

AI API'ye uygun olmayan isler:

- Mustavir onayi olmadan nihai kayit veya export karari.
- Mevzuat yorumu veya gider yazilir/yazilmaz kesin karari.
- KDV, tevkifat, istisna ve iade gibi riskli kararlar.
- Zirve export formatinin kesinligi.

Ilk politika: yeni mukellef, yeni urun ailesi, eksik NACE/faaliyet veya zayif
gecmis veride AI aktif anlamlandirma katmanidir. Daha once mustavir tarafindan
onaylanmis ogrenme kurali, chart semantic map veya research cache yeterli
guven veriyorsa AI tekrar cagrilmaz. Guven dusukse bos sonuc donmek yerine
dolu fis taslagi uretilir; export kapisi review'de kalir.

Soguk baslangic politikasi: gecmis veri yoksa AI taslak hazirlayabilir, ancak
onerilen hesap yalnizca mevcut hesap plani icinden secilir, motor bu secimi
hesap ailesi filtresiyle geri cevirmez ve export kapisi mustavir onayi olmadan
acilmaz. Bu modun ayrintili hazirlik kriterleri
`docs/ai-assisted-draft-readiness.md` dosyasinda tutulur.

Hesap plani baglami tek sabit aday limitiyle kirpilmez. Aday seti kucukken AI
tek cagrida nihai hesap/cari secer; aday seti buyukse iki asamali secim
kullanilir. Ilk asama kompakt hesap aile haritasi ve fatura/NACE baglamiyla
ilgili aileleri belirler, ikinci asama yalniz secilen ailelerin gercek hesap
adaylari ve ilgili `120/320` cari adaylari arasindan secim yaptirir. Her asama
maliyet ve kalite icin `input_chars`, aday sayisi ve karar sonucuyla loglanir.
