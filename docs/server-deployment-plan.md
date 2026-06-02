# Server Deployment Plan

## Karar

Ilk production kurulumu GPU'suz tek kiralik sunucuda baslayacak. Sunucu AI modeli
calistirmayacak; AI ihtiyaci sadece dis API/batch cagriyla karsilanacak.
Varsayilan baslangic saglayici Radore Cloud Server Infinity kabul edilir.

## Onerilen Minimum Sunucu

Pilot ve ilk canli deneme icin:

- Turkiye lokasyon
- 8 vCPU
- 24 GB RAM
- En az 250 GB disk, tercihen buyutulebilir disk
- Ubuntu LTS
- Ayrilmis belge storage klasoru veya volume
- Harici backup hedefi

Varsayilan ilk paket:

- Radore Infinity: 8 vCPU, 24 GB RAM, 250 GB disk.

Buyume hedefi:

- 16 vCPU / 32 GB RAM veya daha yuksek paket.
- Disk/storage ayrica buyutulebilmeli.
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

Ham PDF/XML/ekstre dosyalari 90 gun indirilebilir kalir.

- 0-90 gun: belge indirilebilir ve review ekraninda goruntulenebilir.
- 75. gunden sonra: `storage_status=expiring`.
- 90. gun sonunda: ham dosya silinir, `storage_status=deleted`.
- Metadata, fis taslagi, mustavir karari, learning kaydi ve export izi kalir.

Backup manifestleri 14 gun saklanir. Ham dosya backup kopyasi uzun sureli
saklanmayacak; 90 gunluk urun politikasiyla uyumlu tutulacak.

## Ortam Degiskenleri

Ilk production env:

```text
FISORA_ENV=production
FISORA_STORE_BACKEND=postgres
FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
FISORA_EXPORT_PATH=/opt/fisora/data/exports
DATABASE_URL=postgresql://...
REDIS_URL=redis://redis:6379/0
FISORA_AI_PROVIDER=disabled
FISORA_AI_MONTHLY_CAP_USD=100
FISORA_WORKER_RETENTION_INTERVAL_SECONDS=86400
FISORA_WORKER_PROCESSING_INTERVAL_SECONDS=30
```

AI provider canliya alindiginda `FISORA_AI_PROVIDER` `openai`, `gemini` veya
`manus` gibi bir degere cekilir. Kendi sunucuda model runtime'i kurulmaz.

## Backup Politikasi

Her gece:

- PostgreSQL dump.
- Belge metadata manifest.
- Export paketleri.

Saklama:

- Gunluk: 14 gun.
- Ham belge dosyasi: urun politikasina gore 90 gunu asmayacak.
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

## Yerel Docker Kontrol Notu

2026-06-02 yerel kontrolde:

- `docker --version`: Docker CLI kurulu.
- `docker compose version`: Docker Compose kurulu.
- `docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config`: compose dosyasi
  parse edildi.
- `docker info`: Docker Desktop Service durdugu ve `docker_engine` pipe erisimi reddedildigi icin container
  baslatma testi yapilamadi.
- `C:\Users\kerem\.docker` altinda izin hatasi gorundu; Docker Desktop acildiktan veya kullanici izinleri
  duzeltildikten sonra `docker info` tekrar denenmeli.

Container smoke test icin hedef komut:

```powershell
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml up -d postgres redis
python backend/scripts/apply_migrations.py
python backend/scripts/run_postgres_smoke.py
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml down
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
