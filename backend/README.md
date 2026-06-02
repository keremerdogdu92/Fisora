# Backend

Faz 0 backend'i iki katmandan olusur:

- FastAPI iskeleti: API yonunu sabitler.
- Saf Python domain modulleri: hesap plani importu, fis uretimi ve export
  prototiplerini frontend'den bagimsiz dogrular.

## Kurulum

Python 3.11-3.13 kullanin. Bu repo icin pinlenen `pydantic-core`
surumu Python 3.14 ile wheel bulamazsa Rust/PyO3 derlemesinde takilabilir.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r backend/requirements.txt
```

## Test

```powershell
python -m unittest discover backend/tests
```

## Demo

```powershell
$env:PYTHONPATH="backend"
python backend/scripts/run_phase0_demo.py
```

Demo script'i `exports/` altinda test CSV ciktilari uretir.

Sentetik pilot kosusu, ozel veri kullanmadan onboarding -> hesap plani ->
fatura simulation -> review decision -> export package -> workspace store
akisini tek komutta dener:

```powershell
$env:PYTHONPATH="backend"
python backend/scripts/run_synthetic_pilot.py
```

Varsayilan cikti `exports/synthetic_pilot_store.json` dosyasidir ve repoya
girmez. Export-ready kayitlar icin ayni klasorde
`exports/synthetic_pilot_store_export.csv` uretilir; review'a dusen belgeler
bu CSV'ye girmez.

## Yerel MVP Store

Phase 0 API, kalici demo snapshot'lari icin varsayilan olarak
`exports/phase0_store.json` dosyasini kullanir. `exports/` gitignored oldugu
icin bu dosyaya yazilan musteri/veri denemeleri repoya girmez.

Farkli bir store dosyasi kullanmak icin:

```powershell
$env:FISORA_STORE_PATH="C:\\tmp\\fisora-phase0-store.json"
```

Varsayilan adapter JSON store'dur. Production icin `FISORA_STORE_BACKEND=postgres`
ve `DATABASE_URL` veya `FISORA_DATABASE_URL` verilirse ilk PostgreSQL adapter'i
ayni workspace kontratini `workflow_records` tablosunda saklar.

Schema artik versiyonlu migration runner ile uygulanir:

```powershell
$env:DATABASE_URL="postgresql://fisora:change-me@localhost:5432/fisora"
python backend/scripts/apply_migrations.py
```

Baglanti kurmadan migration planini gormek icin:

```powershell
python backend/scripts/apply_migrations.py --dry-run
```

Bu store su endpointlerin davranisini dogrular:

- `POST /phase0/store/client`
- `POST /phase0/store/chart-accounts`
- `POST /phase0/store/document-upload`
- `POST /phase0/store/document-upload-multipart`
- `POST /phase0/store/document-retention/run`
- `POST /phase0/store/processing/run`
- `GET /phase0/store/processing-jobs/{client_id}`
- `POST /phase0/store/simulation`
- `POST /phase0/store/review-decision`
- `POST /phase0/store/export-package`
- `POST /phase0/store/export-package/from-workspace`
- `GET /phase0/store/workspace/{client_id}`

Gercek auth gelene kadar API mock header ile yetkiyi test eder:

```text
X-Fisora-User-Id: mali-musavir
```

Header yoksa demo geriye donuk calisir. Header varsa `store/workspace`,
`store/clients`, review, export ve upload akislari atanmis portal kullanicisi ve
rolune gore filtrelenir. `client_user` belge yukler; `accountant` veya `admin`
review/export aksiyonu alabilir.

`POST /phase0/store/document-upload` ilk MVP sozlesmesidir. Multipart upload
destegi de eklendi. `document-upload` geriye donuk base64 kontratini korur;
`document-upload-multipart` buyuk dosyalar icin tercih edilecek yoldur. Icerik
gonderilirse dosya `exports/documents/{client_id}/{document_id}/` altina yazilir,
icerik gonderilmezse sadece kuyruk/metaveri kaydi olusur. Production'da storage
adapter local disk yerine sunucu volume'u veya S3-compatible object storage
kullanabilir.

Ham belge retention politikasi 90 gundur. Upload kaydi
`download_available_until`, `expires_at`, `storage_status` ve `deleted_at`
alanlarini tasir. `POST /phase0/store/document-retention/run` suresi dolan ham
dosyalari siler ve metadata kaydini `storage_status=deleted` olarak korur.

Upload sonrasi sistem bir processing job olusturur. Worker su anda:

- Text PDF faturalari mevcut `pypdf` parser'i ile okur.
- E-fatura XML dosyalarindan temel kimlik, tutar, KDV ve kalem ipuclari cikarir.
- CSV/XLSX banka veya POS ekstrelerinden satir bazli tarih, aciklama, tutar ve
  statik islem tipi cikarir.
- Banka/POS satirlarindan dengeli statement fis taslaklari uretir; riskli POS
  ve belirsiz satirlar review'da kalir.
- Banka/POS cari eslestirmesinde IBAN, VKN/TCKN, unvan ve otomasyon adayi
  mustavir learning event'leri sirayla degerlendirilir.
- Hesap plani ve mukellef profili varsa fatura sonucunu simulation motoruna
  gonderir; eksik veya supheli durumlari `review_required` olarak saklar.

PostgreSQL adapter smoke testi icin:

```powershell
$env:DATABASE_URL="postgresql://fisora:change-me@localhost:5432/fisora"
python backend/scripts/run_postgres_smoke.py
```

Bu komut schema uygulanmis gercek Postgres'te client, chart account, upload,
processing job ve workspace okuma akisini dener.

## Production Compose Iskeleti

Ilk production iskeleti kok dizindeki `docker-compose.production.yml` dosyasidir.
Backend, worker, PostgreSQL, Redis, frontend, Nginx ve backup servislerini tarif
eder.

```powershell
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config
```

Ilk compose iskeleti JSON store ile de calisabilir. Production varsayimi
`FISORA_STORE_BACKEND=postgres` olacak; bunun icin
`backend/scripts/apply_migrations.py` calistirilmali ve `DATABASE_URL`
tanimlanmalidir.

## AI Adapter Davranisi

Urun/kalem siniflandirma akisi maliyet kontrollu calisir:

1. Statik kural kutuphanesi once calisir.
2. Statik eslesme yeterince guvenliyse AI cagrilmaz.
3. AI kapaliysa veya provider bagli degilse sistem statik sonuc ile devam eder.
4. Provider baglandiginda sonuc kategori/guven/gerekce iceren JSON schema ile
   dogrulanir.

Ilk yerel endpoint:

- `POST /phase0/classification/product`
- `POST /phase0/classification/batch-benchmark`

Simulation endpointleri `aiClassificationUsed`, `aiClassificationProvider`,
`aiClassificationSkippedReason`, `aiClassificationReason` ve
`aiEstimatedInputChars` alanlarini dondurur. Bu alanlar muhasebe kararini tek
basina vermez; sadece siniflandirma izini ve maliyet sinyalini tasir.

`classification/batch-benchmark` dis API'ye cikmadan statik kurallari veya
replay provider payload'larini ayni schema ile kiyaslar. Gercek OpenAI, Gemini
veya Manus kosulari baglandiginda ayni benchmark yapisi belge basina maliyet ve
dogruluk karsilastirmasi icin kullanilacak.

`store/export-package/from-workspace`, workspace'teki fatura ve statement
sonuclarindan yalnizca dengeli ve risksiz entry'leri export paketine alir.
Review gerekli veya risk bayrakli kayitlar `excluded_document_refs` icinde kalir.
Ayni endpoint `exports/generated/{client_id}/` altinda indirilebilir CSV dosyasi
da uretir; indirme yolu `download_url` alaninda doner.

Export dosyasi adapter katmanindan uretilir. Su an desteklenen adapter'lar:

- `zirve_universal_csv`: ilk aday CSV format.
- `json_manifest`: denetim ve demo icin JSON entry paketi.

Gercek Zirve saha testinden sonra `zirve_verified_format` bu adapter katmanina
eklenecek.
