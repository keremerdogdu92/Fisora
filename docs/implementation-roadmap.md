# Fisora Uygulama Yol Haritasi

## Mevcut Durum

Tamamlanan ana dilimler:

- Muhasebe domain cekirdegi: hesap plani importu, fis taslagi, risk bayraklari.
- Business relevance: faaliyet/NACE baglami, marka-model kategori siniflandirma.
- Cari eslestirme: VKN/TCKN, unvan benzerligi, review fallback.
- Review ve learning modeli: mustavir karari, learning event, otomasyon adayi.
- Export gate: sadece guvenli ve dengeli kayitlar export paketine girer.
- MVP portal: belge listesi, review kuyrugu, export hazir gorunumu.
- API scaffold: onboarding, simulation, review, export, store endpointleri.
- Yerel store: `exports/phase0_store.json` ile ignored demo/pilot snapshot.
- AI adapter: statik kural once, AI sadece belirsiz kalemde, JSON schema guard.
- Sentetik pilot: 3 belgeyle uc uca store + review + export CSV kosusu.
- Learning rule uygulama: mustavir duzeltmesi sonraki benzer belgede oneriyi etkiler.
- Portal ilk UI dilimi: mukellef yukleme alani ve mustavir review calisma masasi.
- Belge upload/storage ilk sozlesmesi: metaveri, local storage path, sha256 ve kuyruk durumu.
- Kendi sunucu yonu: GPU'suz baslangic, AI sadece dis API/batch ve maliyet cap'iyle.
- Server deployment plani: Nginx, Docker Compose, frontend, backend, worker, PostgreSQL, Redis, document volume.
- Retention politikasi: ham PDF/XML/ekstre 90 gun saklanir, metadata ve muhasebe izi korunur.
- Production compose iskeleti: backend, frontend, nginx, worker, postgres, redis ve backup servisleri.
- PostgreSQL adapter ilk surumu: JSON workspace kontrati production database'de `workflow_records` ile saklanabilir.
- Worker queue ilk surumu: upload sonrasi processing job olusur, parser tipi secilir, worker workspace'e guvenli review sonucu yazar.
- Portal job durumu: yuklenen belgelerde parser ve job status gorunur.
- Worker parser baglantisi: text PDF ve e-fatura XML sonucunu simulation motoruna baglar.
- Banka/POS parser ilk surumu: CSV/XLSX ekstre satirlarini GIB, SGK, POS ve belirsiz kategoriye ayirir.
- Portal karar API baglantisi: musavir karar butonlari `store/review-decision` ile kalici learning event uretir.
- PostgreSQL smoke test script'i: schema uygulanmis gercek database'de store ve worker akisini dener.
- Multipart upload ilk surumu: portal dosyalari base64 yerine `FormData` ile API'ye gonderir.
- Banka/POS statement fis taslagi: parse edilen satirlardan dengeli banka fis entry payload'i uretir.
- Review duzeltme formlari: mustavir hesap/cari/gerekce duzeltmesini kararla birlikte API'ye yazar.
- Workspace export package: store'daki guvenli ve dengeli fatura/statement entry'lerinden export paketi uretir.
- AI batch benchmark altyapisi: statik kural ve replay provider payload'lari uzerinden kategori dogruluk/maliyet sinyali hesaplar.
- Export CSV dosya uretimi: workspace export package indirilebilir CSV dosyasina yazilir.
- Review duzeltmesini UI taslagina uygulama: girilen hesap/cari kodlari secili fis satirinda aninda gorunur.
- Review duzeltmesini kalici taslaga uygulama: mustavir onayi workspace refresh sonrasi korunur.
- Export indirme izi: CSV indirildiginde `downloaded_at` ve `download_count` saklanir.
- Docker compose config kontrolu: production compose dosyasi parse edildi; daemon/container smoke testi Docker Desktop izinleri duzelince kosulacak.
- Portal yetki iskeleti: upload icin mukellef onboarding kaydi ve atanmis portal kullanicisi zorunlu hale geldi.
- Banka/POS cari eslestirme: ekstre satirlari VKN/TCKN/unvan uzerinden 120/320 hesap plani adaylarina baglanabilir.
- Client onboarding paketi: mukellef karti, hesap plani ve portal kullanicilari tek API cagrisiyla hazirlanabilir.
- Mukkellef listesi API'si: musavir ekraninin cok-mukellef secimine hazir client listesi saglanir.
- Export manifest dosyasi: CSV ile birlikte audit/icerik manifest JSON'u uretilir ve indirilebilir.
- Versioned migration runner: `backend/db/migrations` altindaki SQL dosyalari checksum ile `schema_migrations` tablosuna islenir.
- Portal cok-mukellef secimi: musavir ekraninda API'deki mukellef listesi secilebilir ve secime gore workspace yenilenir.
- Banka/POS cari eslestirme genislemesi: IBAN ve otomasyon adayi gecmis mustavir kararlari cari eslestirmede kullanilir.
- Mock auth/yetki guard: `X-Fisora-User-Id` header'i ile mukellef, mustavir ve admin rolleri test edilebilir.
- Export adapter ayrimi: universal CSV ve JSON manifest adapter'lari ayrildi; dogrulanmis Zirve formati daha sonra eklenecek.
- Mustavir demo gorusmesi paketi: yarinki gorusme icin demo akisi, istenecek dosyalar ve karar sorulari hazirlandi.

## Siradaki 5 Adim

1. Docker daemon ve PostgreSQL saha smoke testi
   - `backend/scripts/apply_migrations.py` gercek Postgres'e uygulanir.
   - `FISORA_STORE_BACKEND=postgres` ile client -> upload -> worker -> workspace akisi denenir.
   - Compose config ve container start senaryosu sunucuda dogrulanir.

2. Export dosya adapter'i genisletme
   - Zirve saha testinde calisan kolon/format sabitlenir.
   - Manifestteki kolon/entry metadatasi gercek Zirve saha raporuna baglanir.

3. Portal auth ve yetki genisletmesi
   - Gercek login/session provider secilir.
   - Musavir birden cok mukellef gorur.
   - Kullanici listesi ve davet akisi eklenir.

4. Direct object storage hazirligi
   - Sunucu volume'u disinda S3-compatible storage opsiyonu adapter olarak eklenir.
   - 90 gun retention politikasiyla uyumlu download URL akisi planlanir.

5. AI API batch benchmark
   - Statik kuralla cozulmeyen kalemlerde OpenAI/Gemini/Manus adaylari test edilir.
   - Belge basina maliyet ve dogruluk karsilastirilir.

Sonraki saha kilidi: Zirve export formati gercek programda denenmeden "tamam" sayilmaz.

## Genel Kalan Is Haritasi

```mermaid
flowchart TD
    A["MVP domain cekirdegi"] --> B["Musteri onboarding ve hesap plani"]
    B --> C["Mukellef upload portali"]
    C --> D["Belge parse ve invoice line cikarma"]
    D --> E["Kategori, cari ve muhasebe taslagi"]
    E --> F["Risk gate ve mustavir review ekrani"]
    F --> G["Learning rule uygulama"]
    G --> H["Kontrollu export CSV"]
    H --> I["Belge upload ve local storage"]
    I --> J["Gercek pilot veri kosusu"]
    J --> K["Zirve saha dogrulamasi"]
    K --> L["PostgreSQL adapter ve auth"]
    L --> M["AI provider A/B benchmark"]
    M --> N["Canli MVP"]
```

## Kapanmamis Ana Basliklar

- Auth ve yetki: Mock header guard var; gercek login/session provider secilmeli.
- PostgreSQL saha testi: adapter yazildi, Docker daemon izni acilinca gercek Postgres kosusu yapilacak.
- Dosya saklama: PDF/XML/ekstre ve turetilmis JSON/CSV ayrimi, retention politikasi.
- Banka/POS akisi: satir parse, dengeli fis taslagi, VKN/unvan, IBAN ve gecmis karar cari eslestirmesi var.
- Mustavir calisma masasi: karar ve duzeltme API baglantisi var; duzeltme artik kalici taslak ve learning izine uygulanir.
- Zirve format kesinligi: Gercek import dosyasiyla saha testi sart.
- AI provider secimi: OpenAI/Gemini/Manus kararini pilot batch benchmark belirlemeli.
- Maliyet limiti: Belge basina AI cagrisi, token/karakter limiti ve aylik cap.
- Denetim izi: Kim yukledi, kim onayladi, ne degisti, hangi kurala donustu.
