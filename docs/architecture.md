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

Supabase production ana mimari olarak kullanilmayacak. Sadece demo veya hizli
prototip icin opsiyonel tutulabilir.

## Ana Bilesenler

- Auth ve uyelik: serbest kayit yok; kullanicilar mustavir/ofis tarafindan
  acilir ve mukellefe baglanir.
- Mukellef onboarding: mukellef karti, VKN/TCKN, faaliyet/NACE, isyeri adresi,
  Zirve hesap plani ve opsiyonel yevmiye/muavin exportu alir.
- Belge yukleme: fatura, e-fatura XML/PDF, banka ekstresi ve POS ekstresi
  mukellef yetkisine gore yuklenir.
- Parser katmani: OCR kullanmadan once text PDF, XML, Excel ve CSV parser
  calisir. OCR sadece text cikmayan belgelerde fallback olur.
- Product classification: fatura kalemlerindeki marka/model satirlarini urun
  kategorilerine cevirir.
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

## Worker Akisi

```text
belge yuklendi
  -> mukellef yetkisi ve karti dogrula
  -> text/XML/Excel/CSV parse et
  -> fatura/ekstre alanlarini cikar
  -> gerekiyorsa AI ile marka-model ve urun kategorisi siniflandir
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
