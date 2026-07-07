# Server Deployment Plan

## Karar

Ilk production kurulumu GPU'suz tek kiralik sunucuda baslayacak. Sunucu AI modeli
calistirmayacak; AI ihtiyaci sadece dis API/batch cagriyla karsilanacak.

## Onerilen Minimum Sunucu

Alinan pilot sunucu:

- 4 Core 2.70 GHz
- 4 GB DDR4 RAM
- 100 GB NVMe SSD
- Ubuntu LTS
- Ayrilmis belge storage klasoru veya volume
- Ayni makine disi backup hedefi

Buyume hedefi:

- RAM, CPU ve disk/storage ayrica buyutulebilmeli.
- Paket buyutmede veri tasima gerekip gerekmedigi satin alma oncesi yazili
  netlestirilmeli.

## Kurulacak Bilesenler

Sunucu uzerinde Docker Compose ile:

- `nginx`: HTTPS reverse proxy, static frontend routing, upload size limit.
- `frontend`: Next.js app.
- `backend`: FastAPI API.
- `worker`: belge parse, simulation, export hazirlama.
- `postgres`: production database.
- `redis`: worker queue ve job status.
- `backup`: zamanlanmis database dump ve belge manifest yedegi.

Sunucu uzerinde sistem seviyesinde:

- Ubuntu LTS security updates.
- SSH key-only login.
- Firewall: sadece 22, 80, 443 acik.
- Fail2ban veya esdeger brute-force koruma.
- Let's Encrypt TLS.
- Log rotation.
- Disk usage monitor.

## Dizin Yapisi

```text
/opt/fisora
  /app
  /data
    /postgres
    /redis
    /documents
    /exports
    /backups
  /logs
```

Ham belgeler `/opt/fisora/data/documents` altinda tutulur. Veritabaninda sadece
belge metaverisi, storage path, boyut, hash, yukleyen kullanici ve isleme durumu
saklanir.

## Belge Saklama Politikasi

Ham PDF/XML/ekstre dosyalari 90 gun aktif kalir.

- 0-90 gun: belge review ekraninda goruntulenebilir.
- 75. gunden sonra: `storage_status=expiring`.
- 90. gun sonunda: musavire indirme/arsivleme linki, silme onayi ve 90 gun
  uzatma secenegi sunulur. Sessiz otomatik silme uygulanmaz.
- Metadata, fis taslagi, mustavir karari, learning kaydi ve export izi kalir.

Backup manifestleri 14 gun saklanir. Ham dosya backup kopyasi uzun sureli
saklanmayacak; 90 gunluk urun politikasiyla uyumlu tutulacak.

## Ortam Degiskenleri

Ilk production env:

```text
FISORA_ENV=production
FISORA_STORE_BACKEND=postgres
FISORA_AUTH_MODE=session_required
FISORA_AUTH_HEADER=X-Fisora-User-Id
FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
FISORA_EXPORT_PATH=/opt/fisora/data/exports
DATABASE_URL=postgresql://...
REDIS_URL=redis://redis:6379/0
FISORA_AI_PROVIDER=groq
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b
FISORA_AI_MONTHLY_CAP_USD=0.01
GROQ_API_KEY=server-env-only
FISORA_WORKER_RETENTION_INTERVAL_SECONDS=86400
FISORA_WORKER_PROCESSING_INTERVAL_SECONDS=30
```

AI provider mustavir oncesi demo icin dis Groq API uzerinden calisir. Kendi
sunucuda model runtime'i kurulmaz; key sadece kapali server env dosyasinda
tutulur. Ucretli OpenAI kiyasi gerekirse ayni adapter hatti OpenAI env'i ile
calistirilir.

Ilk kapali IP demosunda session katmani hazir degilse
`FISORA_AUTH_MODE=mock_header_required` kullanilir. Ilk MVP hedefi custom
session'dir. `trusted_header` ancak ayri gateway/JWT/OIDC katmani user id'yi
guvenli sekilde dogrulayip backend'e enjekte ederse kullanilir.

## Backup Politikasi

Periyodik veya manuel calistirilan backup:

- PostgreSQL dump.
- Belge metadata manifest.
- Export paketleri.
- Gerekli aktif belge dosyalari.
- Ayni makine disina kopyalama.

Saklama:

- Gunluk: 14 gun.
- Ham belge dosyasi: musavir onayli 90 gun/uzatma politikasina uyacak.
- Metadata/audit/export izleri: database retention politikasina gore kalir.

## Ilk Deploy Sirasi

1. Sunucu alinir ve Ubuntu LTS kurulur.
2. SSH, firewall, TLS ve temel hardening yapilir.
3. Docker ve Docker Compose kurulur.
4. `postgres`, `redis`, `backend`, `worker`, `frontend`, `nginx` compose servisleri hazirlanir.
5. Belge storage ve backup klasorleri olusturulur.
6. Demo/pilot env ile deploy edilir.
7. Versioned migration runner calistirilir:
   `python backend/scripts/apply_migrations.py`
8. PostgreSQL store smoke testi calistirilir:
   `python backend/scripts/run_postgres_smoke.py`
9. Mukellef upload -> worker -> review -> export akisi test edilir.
10. Gercek Zirve export saha testi yapilir.

Detayli canliya gecis checklist'i: `docs/production-deploy-checklist.md`.

## Yerel Docker ve MCP Kontrol Notu

2026-06-03 yerel kontrolde Docker Desktop aktif ve compose smoke testi gecti.

- `docker --version`: Docker `29.5.2`.
- `docker info`: Docker Desktop Linux engine calisiyor.
- Docker MCP Catalog Codex global config'e baglandi: `codex: connected`.
- MCP profilinde `docker-docs` aktif. Bu server Docker dokumantasyonu icindir.
- Docker MCP katalogda yerel daemon/container/compose yoneten ayri server
  bulunmadigi icin container operasyonlari Docker CLI ile surdurulur.
- Docker MCP araclarinin Codex arac listesinde gorunmesi icin Codex uygulamasini
  yeniden baslatmak gerekebilir.

Kosulan compose smoke komutlari:

```powershell
$env:FISORA_HTTP_PORT='8088'
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml up -d postgres redis
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml up --build migrate
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml run --rm migrate python /app/backend/scripts/run_postgres_smoke.py
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml up -d --build backend frontend nginx
```

Sonuclar:

- Postgres ve Redis `healthy`.
- Migration runner `001_initial_schema.sql` ve `002_counterparty_iban.sql`
  migrationlarini uyguladi.
- Postgres smoke sonucu: `status=ok`, `completed_jobs=1`,
  `document_export_status=export_ready`.
- Nginx `http://localhost:8088` uzerinden cevap verdi.
- `GET /health`: `{"status":"ok"}`.
- Frontend ana sayfa HTTP `200`.
- `GET /api/phase0/summary`: Faz 0 summary cevap verdi.

Uctan uca Docker smoke:

1. Nginx uzerinden demo mukellef onboarding paketi olusturuldu.
2. Atanmis portal kullanicisiyle banka ekstresi upload edildi.
3. Worker container'i `FISORA_WORKER_RUN_ONCE=1` ile calistirildi.
4. Job `completed`, belge `export_ready`, fis taslagi `statement_entries_ready`
   ve `draft_line_count=2` oldu.
5. Workspace export package olusturuldu.
6. CSV ve manifest download endpointleri HTTP `200` dondu.
7. Backup job `FISORA_BACKUP_RUN_ONCE=1` ile Postgres dump ve belge manifesti
   uretti.

Backup smoke dosyalari:

```text
postgres-20260603T083426Z.sql
documents-20260603T083426Z.manifest.tsv
```

## Repo Icindeki Ilk Iskelet

- `docker-compose.production.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `deploy/nginx/default.conf`
- `deploy/backup/backup.sh`
- `deploy/production.env.example`

Ilk compose iskeleti JSON store ile calisabilir. PostgreSQL adapter ilk surumu
eklendi; production smoke testte `FISORA_STORE_BACKEND=postgres` ve `DATABASE_URL`
ile calistirilacak. Schema `backend/scripts/apply_migrations.py` ile versiyonlu
uygulanir. Worker upload sonrasi processing job'lari isler ve retention
job'unu ayni servis icinde periyodik calistirir.
