# Server Deployment Plan

## Karar

Ilk production kurulumu GPU'suz tek kiralik sunucuda baslayacak. Sunucu AI modeli
calistirmayacak; AI ihtiyaci sadece dis API/batch cagriyla karsilanacak.

## Onerilen Minimum Sunucu

Pilot ve ilk canli deneme icin:

- 8-12 vCPU
- 16-32 GB RAM
- 512 GB-1 TB NVMe
- Ubuntu LTS
- Ayrilmis belge storage klasoru veya volume
- Harici backup hedefi

Daha guvenli ilk secenek:

- 32 GB RAM
- 1 TB NVMe
- Snapshot/backup destegi
- Avrupa lokasyonu

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
```

AI provider canliya alindiginda `FISORA_AI_PROVIDER` `openai`, `gemini` veya
`manus` gibi bir degere cekilir. Kendi sunucuda model runtime'i kurulmaz.

## Backup Politikasi

Her gece:

- PostgreSQL dump.
- Belge metadata manifest.
- Export paketleri.
- Son 24 saatte yuklenen belgelerin harici backup kopyasi.

Saklama:

- Gunluk: 14 gun.
- Haftalik: 8 hafta.
- Aylik: mustavir/ofis politikasina gore.

## Ilk Deploy Sirasi

1. Sunucu alinir ve Ubuntu LTS kurulur.
2. SSH, firewall, TLS ve temel hardening yapilir.
3. Docker ve Docker Compose kurulur.
4. `postgres`, `redis`, `backend`, `worker`, `frontend`, `nginx` compose servisleri hazirlanir.
5. Belge storage ve backup klasorleri olusturulur.
6. Demo/pilot env ile deploy edilir.
7. Mükellef upload -> worker -> review -> export akisi test edilir.
8. Gercek Zirve export saha testi yapilir.
