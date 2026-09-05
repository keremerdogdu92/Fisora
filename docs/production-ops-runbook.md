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

## Kanonik Production Deploy

Routine production release icin tek yetkili yol GitHub Actions -> AWS OIDC -> `FisoraProductionDeploy` SSM document akışıdır. Production checkout üzerinde normal operasyon sırasında doğrudan `git checkout`, `git reset`, `docker compose up --build` veya genel `AWS-RunShellScript` ile release yapılmaz.

1. `main` branch'ini publish et:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-publish.ps1 -Branch main -Json
```

2. GitHub Actions içinden **Deploy Production** workflow'unu `main` için çalıştır. Workflow yalnızca tetiklenen `GITHUB_SHA` commit'ini restricted SSM document üzerinden deploy eder.

3. SSM document source-of-truth'u repodadır:

```text
deploy/aws/fisora-production-deploy-document.json
```

Bu document değiştiğinde yetkili AWS oturumuyla bir kez senkronize edilir; bu günlük deploy adımı değildir:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/sync-production-deploy-document.ps1
```

Bilinmeyen tracked production worktree değişikliklerinde deploy otomatik reset atmaz. `FISORA_DEPLOY_BLOCKED reason=tracked_worktree_changes` ile değişen dosyaları loglar ve güvenli şekilde durur. Yalnızca OIDC geçişinden kalmış, blob hash'i `7001c451a720f682b5334f97d10dab9643c38180` olan eski `.github/workflows/deploy-production.yml` sürümü tek kirli tracked dosyaysa HEAD sürümüne geri alınır ve `FISORA_DEPLOY_REPAIRED reason=known_legacy_workflow_blob` kaydı üretilir.

## Acil Durum Direct SSH Release

`deploy/scripts/fisora-release.ps1` rutin production deploy için devre dışıdır. Yalnızca GitHub/OIDC yolu kullanılamayan yetkili bir incident response sırasında açık onayla kullanılabilir:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1 -EmergencyOverride -Branch main -Json
```

Server'a dokunmadan acil durum planını görmek için:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1 -PlanOnly -Json
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

Backup her ortamda sürekli çalışan bir servis değildir. Yetkili yaşam döngüsü
ayarı:

```text
FISORA_BACKUP_MODE=disabled|checkpoint|scheduled
```

### Pilot öncesi: `disabled`

Henüz gerçek pilot verisi yokken varsayılan mod `disabled` olur. Normal deploy
backup profile'ını başlatmaz; PostgreSQL dump veya belge archive üretilmez.
Readiness bu durumu `backup.status=not_required` olarak raporlar.

Bu mod test verilerinin sık temizlendiği mevcut hazırlık aşamasıdır. Backup
container'ının bulunmaması hata değildir.

### Protected corpus sonrası: `checkpoint`

35 alış + 15 satış protected corpus freeze kapısını geçtikten sonra env geçici
olarak:

```text
FISORA_BACKUP_MODE=checkpoint
FISORA_BACKUP_COPY_DIR=<sunucu dışı hedef>
FISORA_BACKUP_AGE_RECIPIENT=<public age recipient>
FISORA_BACKUP_OFFHOST_ATTESTED=true
```

olarak ayarlanır ve tek generation alınır:

```bash
sh deploy/scripts/fisora-prod.sh backup-once
```

Checkpoint paketi PostgreSQL dump, gerçek protected-corpus byte'ları,
`SHA256SUMS` ve metadata içerir. Geçici normal test PDF/XML dosyalarını içermez.
Şifreli `.age` paketi sunucu dışındaki operatör bilgisayarına indirilir.

İzole restore kanıtı:

```bash
FISORA_COMPOSE_PROJECT=fisora-restore-check \
  sh deploy/scripts/fisora-prod.sh restore-protected-check \
  /offhost/fisora-backup-...tar.gz.age \
  /secure/age-identity.txt \
  /tmp/fisora-protected-restore \
  postgresql://...@host.docker.internal:5432/fisora_restore
```

Komut paketin hash'lerini doğrular, PostgreSQL dump'ı ayrı database'e yükler,
protected byte'ları ayrı root'a açar ve uygulama-seviyesi corpus verifier'ı
çalıştırır. Başarılı verifier receipt'i readiness volume'una ayrıca kaydedilir:

```bash
sh deploy/scripts/fisora-prod.sh record-restore-verification \
  /tmp/fisora-protected-restore/restore-verification-....json
```

Checkpoint doğrulandıktan sonra schedule kapalı kalır.

### Gerçek pilot: `scheduled`

İlk gerçek pilot faturası kabul edilmeden önce:

```text
FISORA_BACKUP_MODE=scheduled
FISORA_BACKUP_OFFHOST_ATTESTED=true
```

Bu mod günlük şifreli generation içine PostgreSQL, protected corpus ve 90 günlük
aktif normal PDF/XML byte'larını alır. Yerel generation'lar 14 gün, gerçek
off-host generation'lar 30 gün saklanır. Son başarılı generation 26 saatten,
restore kanıtı 30 günden eskiyse readiness gerçek pilotu bloklar.

Kontrol listesi:

- `FISORA_BACKUP_COPY_DIR` farklı bir failure domain'e bağlıdır; aynı
  sunucudaki `backups/offhost` dizini yeterli değildir.
- `FISORA_BACKUP_OFFHOST_ATTESTED=true` yalnızca hedefin gerçekten ayrı failure
  domain'de olduğu operatör tarafından doğrulandıktan sonra verilir; aksi halde
  readiness, kopya receipt'i bulunsa bile gerçek pilotu bloklar.
- Hedefte yalnız şifreli `.age` generation bulunur.
- Private age identity backup container'ında, env'de veya repository'de değildir.
- Success receipt ancak encryption ve off-host copy tamamlandıktan sonra oluşur.
- Restore receipt güncel generation filename ve digest'iyle eşleşir.
- Backup ve belge storage disk kullanımı beklenmeyen artış göstermiyordur.

Mevcut restart-loop dump'larının silinmesi deploy'un parçası değildir. Kesin
volume, file count, date range ve toplam size gösterildikten sonra ayrı canlı
cleanup onayı gerektirir.

Gerçek `TEMIZLE` işleminden önce
`GET /api/phase0/store/admin/test-reset/preview` ile silinecek operasyonel
kayıtlar ve korunacak corpus/reference/rule sayıları karşılaştırılır. Korumalı
kaynak volume'u normal belge/export volume'larından ayrıdır ve reset tarafından
temizlenmez.

## Belge Saklama Operasyonu

Ham belgeler 90 gun sonunda sessizce silinmez. Once operasyon ekraninda
saklama onizlemesi alinir:

```text
POST /api/phase0/store/document-retention/preview
```

Musavir kontrolunden sonra iki islemden biri uygulanir:

```text
POST /api/phase0/store/document-retention/action
```

Payload ornekleri:

```json
{"document_refs":["client-1:doc-1"],"action":"extend_90_days","delete_files":true}
{"document_refs":["client-1:doc-1"],"action":"delete","delete_files":true}
```

Kural: musteriye geri indirme acilmaz; musteri sadece onizleyebilir.
Gerekirse indirme/arsivleme musavir operasyonu olarak ayrica yapilir.

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
