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

## Siradaki 5 Adim

1. PostgreSQL saha smoke testi calistirma
   - `backend/db/schema.sql` gercek Postgres'e uygulanir.
   - `FISORA_STORE_BACKEND=postgres` ile client -> upload -> worker -> workspace akisi denenir.
   - Compose config ve container start senaryosu sunucuda dogrulanir.

2. Review duzeltmelerini taslaga uygulama
   - Musavirin girdigi hesap/cari duzeltmesi mevcut fis taslagi uzerinde aninda gorunur.
   - Duzeltme sonraki benzer belgeye learning rule olarak uygulanir.

3. Export dosya adapter'i genisletme
   - Workspace export package sonucundan gercek CSV dosyasi uretilir.
   - Zirve saha testinde calisan kolon/format sabitlenir.

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

- Auth ve yetki: Serbest uyelik yok; kullanici bastan mukellefe bagli olmali.
- PostgreSQL saha testi: adapter yazildi, gercek Postgres kosusu henuz yapilmadi.
- Dosya saklama: PDF/XML/ekstre ve turetilmis JSON/CSV ayrimi, retention politikasi.
- Banka/POS akisi: satir parse ve dengeli fis taslagi var; export gate ve cari eslestirme genisleyecek.
- Mustavir calisma masasi: karar ve duzeltme API baglantisi var; duzeltmenin fis taslagina aninda uygulanmasi genisleyecek.
- Zirve format kesinligi: Gercek import dosyasiyla saha testi sart.
- AI provider secimi: OpenAI/Gemini/Manus kararini pilot batch benchmark belirlemeli.
- Maliyet limiti: Belge basina AI cagrisi, token/karakter limiti ve aylik cap.
- Denetim izi: Kim yukledi, kim onayladi, ne degisti, hangi kurala donustu.
