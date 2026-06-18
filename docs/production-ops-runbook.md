# Production Ops Runbook

## Amac

Bu runbook, server kiralandiktan sonra Fisora production stack'ini ayni
komutlarla kurmak, kontrol etmek, backup almak ve sorun aninda log/restore
akisini bilmek icindir.

## Ilk Kurulum

0. Server'a girdikten sonra OS ve Docker durumunu kontrol et:

```bash
cat /etc/os-release
docker --version
docker compose version
```

Docker yoksa once Ubuntu LTS icin Docker Engine kurulumu tamamlanir.

1. Repo server'a alin:

```bash
mkdir -p /opt/fisora
cd /opt/fisora
git clone <repo-url> app
cd app
```

2. Env dosyasini hazirla:

```bash
cp deploy/production.env.example deploy/production.env
```

3. `deploy/production.env` icinde mutlaka degistir:

```text
POSTGRES_PASSWORD=...
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
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
CEREBRAS_API_KEY=...
```

`GROQ_API_KEY`, `OPENROUTER_API_KEY` ve `CEREBRAS_API_KEY` chat'e, GitHub'a
veya commit'e yazilmaz; yalnizca serverdaki `deploy/production.env` dosyasinda
tutulur.

4. Compose config kontrolu:

```bash
sh deploy/scripts/fisora-prod.sh check
```

5. Stack deploy:

```bash
sh deploy/scripts/fisora-prod.sh deploy
```

6. Smoke test:

```bash
sh deploy/scripts/fisora-prod.sh smoke
```

## Gunluk Operasyon Komutlari

Servisleri gormek:

```bash
sh deploy/scripts/fisora-prod.sh ps
```

Backend loglari:

```bash
sh deploy/scripts/fisora-prod.sh logs backend
```

Worker loglari:

```bash
sh deploy/scripts/fisora-prod.sh logs worker
```

Tek seferlik backup:

```bash
sh deploy/scripts/fisora-prod.sh backup-once
```

Windows/local health kontrolu:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-health.ps1 `
  -BaseUrl http://localhost:8088
```

## Backup ve Restore

Backup container su dosyalari uretir:

```text
postgres-YYYYMMDDTHHMMSSZ.sql
documents-YYYYMMDDTHHMMSSZ.manifest.tsv
```

Restore komutu sadece acil durum icindir:

```bash
sh deploy/scripts/fisora-prod.sh restore-postgres /path/to/postgres-YYYYMMDDTHHMMSSZ.sql
```

Restore mevcut database icerigini degistirir. Once yeni backup alinmadan
calistirilmaz.

## Readiness Kontrolu

API:

```text
GET /api/phase0/store/system/readiness
```

Bu payload'da su alanlar izlenir:

- auth modu
- document/export storage yazilabilirligi
- backup var mi
- belge/export/backup boyutlari
- disk doluluk orani
- AI provider ve cap durumu
- Zirve adapter dogrulama durumu

## Server Gelmeden Once Hazir Olanlar

- Docker Compose production stack.
- Migration runner.
- Postgres smoke test.
- Backup job.
- Readiness endpoint.
- Admin readiness paneli.
- Health/check/deploy/backup/log/restore scriptleri.

## Server Gelince Kapanacak Kilitler

- Domain, TLS ve firewall.
- Gercek volume path ve disk izleme.
- Production env secret degerleri.
- Ilk backup dosyasinin olustugunun gorulmesi.
- Gercek URL uzerinden upload, worker, review ve export smoke.
