# Fisero Yedekleme Yaşam Döngüsü Uygulama Planı

**Durum:** Yerel uygulama ve doğrulama tamamlandı; release onayı bekleniyor.

**Uygulama sonucu:** Backend readiness off-host failure domain teyidini
`FISORA_BACKUP_OFFHOST_ATTESTED=true` ile zorunlu tutuyor. Scheduled
`documents.tar` yalnız `.pdf` ve `.xml` dosyalarını alıyor; sentetik TXT
dosyasının dışarıda kaldığı container içinde doğrulandı. Son tam kanıt backend
`566 OK (skipped=20)`, frontend `147/147`, Next.js production build, Compose
config/profile, shell syntax ve `git diff --check` başarısıdır.

> **Agent çalışma gereksinimi:** Bu plan görev görev uygulanırken
> `superpowers:executing-plans` kullanılmalıdır. Adımlar checkbox (`- [ ]`)
> biçiminde takip edilir. Bu çalışma için subagent kullanılmayacaktır.

**Amaç:** Pilot öncesi gereksiz periyodik yedeklemeyi kapatmak, protected corpus
sonrası doğrulanabilir tek checkpoint üretmek ve gerçek pilot öncesinde tam
scheduled yedeklemeyi güvenli biçimde etkinleştirecek yaşam döngüsünü kurmak.

**Mimari:** `FISORA_BACKUP_MODE=disabled|checkpoint|scheduled` tek yetkili yaşam
döngüsü ayarıdır. Backend readiness bu moda ve doğrulanmış backup receipt'lerine
göre karar verir; Docker Compose backup servisini yalnız `scheduled` modda
başlatır; `checkpoint` aynı paketleme kodunu one-shot çalıştırır. Paketleme
PostgreSQL, protected corpus ve moda göre aktif normal belge byte'larını geçici
staging alanında toplar, hash'ler, şifreler ve başarılı off-host kopyadan sonra
atomik receipt üretir.

**Teknoloji:** Python 3, FastAPI domain kodu, POSIX shell, Docker Compose,
PostgreSQL 16 client, `age`, `tar`, Python `unittest`, Node test runner.

## Global Kısıtlar

- Plan ve dokümantasyon Türkçe; code identifier, env adı ve schema alanı
  İngilizce kalır.
- Varsayılan pre-pilot modu `disabled` olur.
- `FISORA_REAL_DATA_PILOT_ENABLED=true` iken `scheduled` dışındaki modlar
  readiness'i bloklar.
- Yerel SQL dosyasının varlığı tek başına backup başarısı sayılmaz.
- `checkpoint` normal test PDF/XML byte'larını içermez.
- `scheduled` aktif normal PDF/XML byte'larını gerçek archive olarak içerir.
- Başarı receipt'i yalnız şifreleme ve hedefe kopya tamamlandıktan sonra yazılır.
- Private `age` identity repository, production env, container veya backup
  paketine girmez.
- Mevcut canlı dump'lar bu plan kapsamında silinmez.
- Commit, push, deploy ve canlı cleanup ayrı onay sınırlarıdır; görev sonunda
  staging veya commit yapılmaz.

---

## Hedef Dosya Yapısı

- Değiştir: `backend/app/domain/system_health.py`
  - backup mode doğrulama, receipt okuma, freshness ve restore durumu.
- Değiştir: `backend/app/domain/production_readiness.py`
  - lifecycle mode'u pilot, real-data ve QNB kapılarına bağlama.
- Değiştir: `backend/tests/test_phase0_domain.py`
  - üç modun readiness regression testleri.
- Değiştir: `backend/tests/test_protected_corpus_backup_contract.py`
  - shell, Compose, env ve document-byte contract testleri.
- Değiştir: `deploy/backup/backup.sh`
  - staging, mode-scope archive, encryption, copy ve receipt.
- Değiştir: `deploy/scripts/fisora-prod.sh`
  - mode validation, scheduled profile activation ve one-shot checkpoint.
- Değiştir: `docker-compose.production.yml`
  - backup profile ve mode env wiring.
- Değiştir: `deploy/production.env.example`
  - güvenli pre-pilot varsayılanları.
- Değiştir: `docs/production-ops-runbook.md`
  - disabled/checkpoint/scheduled prosedürü.
- Değiştir: `docs/open-questions.md`
  - “mekanizma var” ile “operasyon kanıtlı” durumunu ayırma.
- Değiştir: `docs/current-handoff.md`
  - yalnız yerel uygulama ve doğrulama kanıtını, canlı kapıyı açık bırakarak
    kaydetme.

---

### Görev 1: Moda Duyarlı Yedek Sağlığı ve Hazırlık

**Dosyalar:**

- Değiştir: `backend/tests/test_phase0_domain.py`
- Değiştir: `backend/app/domain/system_health.py`
- Değiştir: `backend/app/domain/production_readiness.py`

**Interface:**

- Girdi:
  `backup_health(*, backup_path: Path | str, mode: str, now: datetime | None = None)`.
- Çıktı: mevcut count/path alanlarına ek olarak
  `mode`, `required`, `status`, `service_state`, `latest_attempt_at`,
  `latest_success_at`, `latest_encrypted_generation`,
  `latest_generation_digest`, `offhost_copy_status`,
  `offhost_target_attested`,
  `restore_verified_at`, `blocking`, `warnings`, `ok`.
- Receipt dosyası:
  `backup-success-<timestamp>.json`.
- Restore receipt dosyası:
  `restore-verified-<timestamp>.json`.

- [x] **Adım 1: Üç lifecycle modu için failing readiness testlerini yaz**

`backend/tests/test_phase0_domain.py` içine şu davranışları ayrı testler olarak
ekle:

```python
def test_backup_disabled_is_not_required_before_real_data(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        payload = production_readiness_payload(
            document_storage_path=base / "documents",
            export_path=base / "exports",
            backup_path=base / "backups",
            env={
                "FISORA_AUTH_MODE": "mock_header_required",
                "FISORA_STORE_BACKEND": "postgres",
                "DATABASE_URL": "postgresql://test",
                "FISORA_BACKUP_MODE": "disabled",
            },
        )
    self.assertEqual(payload["backup"]["status"], "not_required")
    self.assertFalse(payload["backup"]["required"])
    self.assertNotIn("backup_missing", payload["warnings"])
    self.assertNotIn("backup_available", payload["pilot_checks"])


def test_real_data_pilot_requires_scheduled_backup_mode(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        payload = production_readiness_payload(
            document_storage_path=base / "documents",
            export_path=base / "exports",
            backup_path=base / "backups",
            env={
                "FISORA_AUTH_MODE": "session_required",
                "FISORA_SESSION_COOKIE_SECURE": "true",
                "FISORA_STORE_BACKEND": "postgres",
                "DATABASE_URL": "postgresql://test",
                "FISORA_REAL_DATA_PILOT_ENABLED": "true",
                "FISORA_REAL_DATA_ACCESS_MODE": "restricted_network",
                "FISORA_BACKUP_MODE": "disabled",
            },
        )
    self.assertFalse(payload["real_data_pilot"]["allowed"])
    self.assertIn("scheduled_backup_mode", payload["real_data_pilot"]["blocking"])


def test_scheduled_backup_requires_fresh_receipt_and_restore_proof(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        backup_path = base / "backups"
        backup_path.mkdir()
        payload = production_readiness_payload(
            document_storage_path=base / "documents",
            export_path=base / "exports",
            backup_path=backup_path,
            env={
                "FISORA_AUTH_MODE": "session_required",
                "FISORA_STORE_BACKEND": "postgres",
                "DATABASE_URL": "postgresql://test",
                "FISORA_BACKUP_MODE": "scheduled",
            },
        )
    self.assertEqual(payload["backup"]["status"], "missing")
    self.assertIn("backup_generation_missing", payload["backup"]["blocking"])
```

- [x] **Adım 2: Hedefli testleri çalıştır ve kırmızı sonucu doğrula**

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_backup_disabled_is_not_required_before_real_data
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_real_data_pilot_requires_scheduled_backup_mode
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_scheduled_backup_requires_fresh_receipt_and_restore_proof
```

Beklenen: yeni signature ve lifecycle alanları bulunmadığı için testler fail.

- [x] **Adım 3: `backup_health` lifecycle contract'ını uygula**

`backend/app/domain/system_health.py` içinde:

```python
BACKUP_MODES = {"disabled", "checkpoint", "scheduled"}


def _read_json_receipt(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def backup_health(
    *,
    backup_path: Path | str,
    mode: str,
    now: datetime | None = None,
) -> dict[str, object]:
    checked_at = now or datetime.now(UTC)
    normalized_mode = mode.strip().lower()
    if normalized_mode not in BACKUP_MODES:
        return {
            "ok": False,
            "mode": normalized_mode or "invalid",
            "required": True,
            "status": "failing",
            "service_state": "configuration_error",
            "blocking": ["backup_mode_invalid"],
            "warnings": [],
            "checked_at": checked_at.isoformat(timespec="seconds"),
        }
    if normalized_mode == "disabled":
        return {
            "ok": True,
            "mode": "disabled",
            "required": False,
            "status": "not_required",
            "service_state": "not_started",
            "latest_attempt_at": None,
            "latest_success_at": None,
            "latest_encrypted_generation": None,
            "latest_generation_digest": None,
            "offhost_copy_status": "not_required",
            "restore_verified_at": None,
            "blocking": [],
            "warnings": [],
            "checked_at": checked_at.isoformat(timespec="seconds"),
        }
```

Checkpoint/scheduled dallarında en yeni geçerli success ve restore receipt'ini
oku. Success receipt yoksa `backup_generation_missing`; receipt 26 saatten
eskiyse `backup_generation_stale`; `offhost_copy_status != "complete"` ise
`offhost_copy_incomplete`; açık failure-domain teyidi yoksa
`offhost_target_unattested`; scheduled modda restore receipt yoksa
`restore_verification_missing`, 30 günden eskiyse
`restore_verification_stale` üret. Checkpoint modunda restore kanıtını aynı
şekilde zorunlu tut.

- [x] **Adım 4: Production readiness'i lifecycle sonucuna bağla**

`backend/app/domain/production_readiness.py` içinde:

```python
backup_mode = source.get("FISORA_BACKUP_MODE", "disabled").strip().lower() or "disabled"
backup = backup_health(backup_path=backup_path, mode=backup_mode)
scheduled_backup_mode = backup_mode == "scheduled"
recoverable_backup = bool(backup["ok"]) and scheduled_backup_mode
```

Pilot öncesi `pilot_checks` içinden `backup_available` zorunluluğunu kaldır.
`real_data_pilot_checks` ve `qnb_pilot_checks` içine ayrı olarak:

```python
"scheduled_backup_mode": scheduled_backup_mode,
"recoverable_backup": recoverable_backup,
```

ekle. `backup_missing` warning'ini yalnız `backup["required"]` doğru ve
`backup["ok"]` yanlışsa üret. Unknown mode için `backup_mode_invalid` blocking
ve warning görünür olsun.

- [x] **Adım 5: Eski readiness test fixture'larını yeni sözleşmeye uyarla**

AI/provider, auth veya export davranışını test eden mevcut fixture'larda sırf
yerel SQL dosyası oluşturarak backup green üretme varsayımını kaldır. Bu
testlerde backup kapsam dışıysa env'e:

```python
"FISORA_BACKUP_MODE": "disabled",
```

ekle. Gerçek pilotu “allowed” bekleyen test scheduled receipt/restore fixture'ı
üretmeli; disabled moda güvenmemelidir.

- [x] **Adım 6: Görev 1 testlerini çalıştır**

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Beklenen: tüm `test_phase0_domain` testleri pass.

- [x] **Adım 7: Görev 1 inceleme kontrol noktası**

```powershell
git diff -- backend/app/domain/system_health.py backend/app/domain/production_readiness.py backend/tests/test_phase0_domain.py
git diff --check
```

Beklenen: yalnız lifecycle/readiness değişiklikleri; staging veya commit yok.

---

### Görev 2: Güvenli Checkpoint ve Zamanlanmış Paketleme

**Dosyalar:**

- Değiştir: `backend/tests/test_protected_corpus_backup_contract.py`
- Değiştir: `deploy/backup/backup.sh`

**Interface:**

- Girdi env:
  `FISORA_BACKUP_MODE`, `DATABASE_URL`, `FISORA_BACKUP_DIR`,
  `FISORA_DOCUMENT_STORAGE_PATH`, `FISORA_PROTECTED_CORPUS_PATH`,
  `FISORA_BACKUP_COPY_DIR`, `FISORA_BACKUP_AGE_RECIPIENT`,
  `FISORA_BACKUP_KEEP_DAYS`, `FISORA_BACKUP_OFFHOST_KEEP_DAYS`.
- Çıktı:
  `fisora-backup-<timestamp>.tar.gz.age`,
  `backup-success-<timestamp>.json`.
- `checkpoint` package:
  `postgres.sql`, `protected-corpus.tar`, `SHA256SUMS`, `metadata.json`.
- `scheduled` package:
  checkpoint içeriğine ek `documents.tar`.

- [x] **Adım 1: Shell contract için failing testleri yaz**

`backend/tests/test_protected_corpus_backup_contract.py` içine:

```python
def test_backup_script_uses_mode_staging_and_success_receipt(self) -> None:
    script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
    self.assertIn('BACKUP_MODE="${FISORA_BACKUP_MODE:-disabled}"', script)
    self.assertIn("mktemp -d", script)
    self.assertIn("trap cleanup", script)
    self.assertIn("backup-success-", script)
    self.assertIn("offhost_copy_status", script)


def test_scheduled_backup_archives_real_document_bytes(self) -> None:
    script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
    self.assertIn('if [ "$BACKUP_MODE" = "scheduled" ]', script)
    self.assertIn("documents.tar", script)
    self.assertIn("-iname '*.pdf'", script)
    self.assertIn("-iname '*.xml'", script)
    self.assertIn('-T "$stage/documents.list"', script)


def test_checkpoint_does_not_archive_disposable_documents(self) -> None:
    script = (ROOT / "deploy" / "backup" / "backup.sh").read_text(encoding="utf-8")
    self.assertIn("checkpoint", script)
    self.assertIn("scheduled", script)
    self.assertNotIn("documents-$stamp.manifest.tsv", script)
```

- [x] **Adım 2: Contract testini kırmızı çalıştır**

```powershell
python -m unittest backend.tests.test_protected_corpus_backup_contract
```

Beklenen: mode, staging, `documents.tar` ve receipt henüz olmadığı için fail.

- [x] **Adım 3: Backup scriptini fail-closed staging akışına dönüştür**

`deploy/backup/backup.sh` şu sırayı uygulasın:

```sh
BACKUP_MODE="${FISORA_BACKUP_MODE:-disabled}"

case "$BACKUP_MODE" in
  checkpoint|scheduled) ;;
  disabled)
    echo "backup mode disabled; no generation created"
    exit 0
    ;;
  *)
    echo "invalid FISORA_BACKUP_MODE: $BACKUP_MODE" >&2
    exit 2
    ;;
esac

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${FISORA_BACKUP_COPY_DIR:?FISORA_BACKUP_COPY_DIR is required}"
: "${FISORA_BACKUP_AGE_RECIPIENT:?FISORA_BACKUP_AGE_RECIPIENT is required}"

stage="$(mktemp -d "$BACKUP_DIR/.backup-stage.XXXXXX")"
cleanup() {
  rm -rf "$stage"
}
trap cleanup EXIT HUP INT TERM
```

`run_backup` içinde PostgreSQL ve protected corpus'u stage alanına yaz. Protected
root yoksa boş archive yerine hata üret. Yalnız `scheduled` modda document root
varsa:

```sh
(cd "$DOCUMENT_DIR" && find . -type f \( -iname '*.pdf' -o -iname '*.xml' \) \
  -print > "$stage/documents.list")
tar -cf "$stage/documents.tar" -C "$DOCUMENT_DIR" -T "$stage/documents.list"
```

üret. `metadata.json` yalnız mode, format version ve timestamp içersin; DSN,
secret veya belge içeriği içermesin.

- [x] **Adım 4: Hash, encryption, copy ve atomik receipt uygula**

Stage içindeki gerçek payload dosyaları için `SHA256SUMS` üret. Önce stage'i
`$BACKUP_DIR/.fisora-backup-$stamp.tar.gz.tmp` dosyasına paketle; ardından:

```sh
local_encrypted="$BACKUP_DIR/fisora-backup-$stamp.tar.gz.age"
offhost_encrypted="$FISORA_BACKUP_COPY_DIR/fisora-backup-$stamp.tar.gz.age"
age -r "$FISORA_BACKUP_AGE_RECIPIENT" -o "$local_encrypted.tmp" "$bundle"
mv "$local_encrypted.tmp" "$local_encrypted"
cp "$local_encrypted" "$offhost_encrypted.tmp"
mv "$offhost_encrypted.tmp" "$offhost_encrypted"
digest="$(sha256sum "$local_encrypted" | awk '{print $1}')"
```

Copy tamamlandıktan sonra JSON receipt'i `.tmp` dosyasına yazıp atomik `mv` ile
yayınla. Receipt yalnız basename, digest, mode, UTC timestamp ve
`offhost_copy_status=complete` taşısın.

- [x] **Adım 5: Retention'ı yalnız complete generation'lara uygula**

`find` cleanup yalnız `fisora-backup-*.tar.gz.age` ve
`backup-success-*.json` dosyalarını `FISORA_BACKUP_KEEP_DAYS` sınırına göre
temizlesin. En yeni success receipt ve onun generation'ı korunmadan cleanup
çalışmamalı. `scheduled` modda off-host target içindeki şifreli generation'lar
`FISORA_BACKUP_OFFHOST_KEEP_DAYS=30` sınırına göre temizlensin; `checkpoint`
modunda tek checkpoint otomatik silinmesin. Stage cleanup her failure'da trap
ile çalışmalı.

- [x] **Adım 6: Contract ve shell syntax doğrulamasını çalıştır**

```powershell
python -m unittest backend.tests.test_protected_corpus_backup_contract
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml run --rm --entrypoint sh backup -n /usr/local/bin/fisora-backup.sh
```

Beklenen: unittest pass; shell syntax exit `0`.

- [x] **Adım 7: Sentetik checkpoint/scheduled smoke çalıştır**

Geçici PostgreSQL ve sentetik dosya root'larıyla:

1. checkpoint generation üret;
2. decrypt edip `documents.tar` bulunmadığını doğrula;
3. scheduled generation üret;
4. decrypt edip sentetik PDF/XML byte'larının `documents.tar` içinde olduğunu
   doğrula;
5. iki receipt'in de yalnız şifreleme ve copy sonrası oluştuğunu doğrula.

Gerçek fatura veya production DSN kullanma.

- [x] **Adım 8: Görev 2 inceleme kontrol noktası**

```powershell
git diff -- deploy/backup/backup.sh backend/tests/test_protected_corpus_backup_contract.py
git diff --check
```

Beklenen: secret veya gerçek belge yok; staging veya commit yok.

---

### Görev 3: Compose Profili ve Operasyon Komutları

**Dosyalar:**

- Değiştir: `backend/tests/test_protected_corpus_backup_contract.py`
- Değiştir: `docker-compose.production.yml`
- Değiştir: `deploy/production.env.example`
- Değiştir: `deploy/scripts/fisora-prod.sh`

**Interface:**

- Backup Compose profile adı: `backup`.
- `deploy`:
  `scheduled` ise `--profile backup up -d`; diğer modlarda backup servisini
  stop eder ve normal stack'i başlatır.
- `backup-once`: yalnız `checkpoint|scheduled` modlarında explicit service run.
- `record-restore-verification <verifier.json>`: yalnız başarılı isolated
  verifier çıktısını backup volume'a atomik receipt olarak kaydeder.

- [x] **Adım 1: Compose ve ops için failing static contract testlerini yaz**

```python
def test_backup_service_is_profile_gated_and_mode_is_wired(self) -> None:
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    self.assertIn('profiles: ["backup"]', compose)
    self.assertIn("FISORA_BACKUP_MODE: ${FISORA_BACKUP_MODE:-disabled}", compose)


def test_production_env_defaults_backup_to_disabled(self) -> None:
    env_example = (ROOT / "deploy" / "production.env.example").read_text(encoding="utf-8")
    self.assertIn("FISORA_BACKUP_MODE=disabled", env_example)


def test_ops_script_starts_profile_only_for_scheduled_mode(self) -> None:
    script = (ROOT / "deploy" / "scripts" / "fisora-prod.sh").read_text(encoding="utf-8")
    self.assertIn('backup_mode="', script)
    self.assertIn("--profile backup", script)
    self.assertIn("compose stop backup", script)
```

- [x] **Adım 2: Static contract testlerini kırmızı çalıştır**

```powershell
python -m unittest backend.tests.test_protected_corpus_backup_contract
```

Beklenen: profile/mode/ops contract henüz olmadığı için fail.

- [x] **Adım 3: Compose env wiring ve profile ekle**

Backend ve backup service environment alanına:

```yaml
FISORA_BACKUP_MODE: ${FISORA_BACKUP_MODE:-disabled}
```

ekle. Backup service'e:

```yaml
profiles: ["backup"]
```

ekle. `deploy/production.env.example` içine:

```text
FISORA_BACKUP_MODE=disabled
FISORA_BACKUP_OFFHOST_KEEP_DAYS=30
```

ekle. Gerçek recipient veya off-host path ekleme.

- [x] **Adım 4: Ops wrapper'da mode parser ve deploy davranışını uygula**

Scriptte yalnız exact env key okuyan helper kullan:

```sh
env_value() {
  key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

backup_mode="$(env_value FISORA_BACKUP_MODE)"
backup_mode="${backup_mode:-disabled}"
```

`deploy` içinde:

```sh
case "$backup_mode" in
  scheduled)
    compose --profile backup up -d
    ;;
  disabled|checkpoint)
    compose up -d
    compose stop backup >/dev/null 2>&1 || true
    ;;
  *)
    echo "Invalid FISORA_BACKUP_MODE: $backup_mode" >&2
    exit 2
    ;;
esac
```

`backup-once` yalnız checkpoint/scheduled modunu kabul etsin ve açıkça
`compose --profile backup run --rm -e FISORA_BACKUP_RUN_ONCE=1 backup`
çalıştırsın.

`restore-protected-check` başarılı olduğunda restore dizinine secret içermeyen:

```json
{
  "status": "verified",
  "verified_at": "2026-07-23T00:00:00+00:00",
  "generation_file": "fisora-backup-....tar.gz.age",
  "generation_digest": "<sha256>"
}
```

receipt'i yazsın. Ayrı `record-restore-verification` komutu bu JSON'u schema,
status ve generation digest açısından doğrulayıp backup volume'a
`restore-verified-<timestamp>.json` olarak atomik kaydetsin. Isolated restore
başarısızsa receipt üretilmemeli.

- [x] **Adım 5: Compose ve shell syntax doğrula**

```powershell
docker compose --profile backup --env-file deploy/production.env.example -f docker-compose.production.yml config --quiet
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config --services
docker compose --profile backup --env-file deploy/production.env.example -f docker-compose.production.yml config --services
```

Beklenen: ilk komut exit `0`; normal service listesinde backup yok, profile
listesinde backup var.

`fisora-prod.sh` syntax:

```powershell
docker run --rm -v "${PWD}:/repo" -w /repo alpine:3.20 sh -n deploy/scripts/fisora-prod.sh
```

Beklenen: exit `0`.

- [x] **Adım 6: Görev 3 gerileme testlerini çalıştır**

```powershell
python -m unittest backend.tests.test_protected_corpus_backup_contract
python -m unittest backend.tests.test_phase0_domain
```

Beklenen: iki test modülü pass.

- [x] **Adım 7: Görev 3 inceleme kontrol noktası**

```powershell
git diff -- docker-compose.production.yml deploy/production.env.example deploy/scripts/fisora-prod.sh backend/tests/test_protected_corpus_backup_contract.py
git diff --check
```

Beklenen: backup service varsayılan stack'ten profile arkasına alınmış; staging
ve commit yok.

---

### Görev 4: Türkçe Operasyon Dokümantasyonu ve Süreklilik

**Dosyalar:**

- Değiştir: `docs/production-ops-runbook.md`
- Değiştir: `docs/open-questions.md`
- Değiştir: `docs/current-handoff.md`

**Interface:**

- Durum adları:
  `mekanizma_hazır`, `pre_pilot_disabled`, `checkpoint_pending`,
  `checkpoint_verified`, `scheduled_pending`, `scheduled_active`.
- Canlı durum hiçbir yerde yalnız `backup kapandı` diye özetlenmez.

- [x] **Adım 1: Runbook'u üç moda göre güncelle**

`docs/production-ops-runbook.md` içinde:

- pre-pilot için `FISORA_BACKUP_MODE=disabled`;
- corpus freeze sonrası geçici `checkpoint`;
- `backup-once`, encrypted paketi workstation'a indirme ve isolated restore;
- gerçek pilot öncesi `scheduled`;
- normal PDF/XML byte kapsamı;
- `age` private identity sınırı;
- mevcut restart-loop dump cleanup'ının ayrı onay gerektirdiği

açık ve Türkçe yazılsın.

- [x] **Adım 2: Açık karar durumunu düzelt**

`docs/open-questions.md` içinde “Manuel backup planı (`kapandı`)" ifadesini
şu ayrımla değiştir:

- mekanizma ve local verification tamamlandı;
- pre-pilot schedule bilinçli olarak disabled;
- corpus checkpoint corpus freeze sonrasına planlı;
- scheduled off-host backup gerçek pilot öncesi kapı;
- live cleanup ayrı operasyon.

- [x] **Adım 3: Handoff'a yalnız doğrulanmış yerel sonucu yaz**

`docs/current-handoff.md` üstüne 2026-07-23 kaydı ekle:

- lifecycle uygulaması yerel;
- hangi testler gerçekten geçti;
- canlı server henüz değişmedi;
- mevcut restart loop ve dump dosyaları deploy/cleanup onayı bekliyor;
- commit/push/deploy yapılmadı.

Uygulama tamamlanmadan test sonucu veya canlı kapanış iddiası yazma.

- [x] **Adım 4: Doküman tutarlılık taraması yap**

```powershell
rg -n -i "backup.*kapandı|yedek.*kapandı|FISORA_BACKUP_MODE|checkpoint|scheduled" docs
git diff --check
```

Beklenen: eski tek-durum anlatımı kalmaz; lifecycle terminolojisi Türkçe
açıklamalarla tutarlıdır.

- [x] **Adım 5: Görev 4 inceleme kontrol noktası**

```powershell
git diff -- docs/production-ops-runbook.md docs/open-questions.md docs/current-handoff.md
```

Beklenen: yalnız doğrulanmış yerel durum; staging veya commit yok.

---

### Görev 5: Tam Yerel Kanıt ve Yayın Ön Kontrolü

**Dosyalar:**

- Bu görev yeni kaynak değişikliği üretmez; yalnız doğrulama ve yayın ön
  kontrolü yapar.

- [x] **Adım 1: Backend tam test suite'ini çalıştır**

```powershell
python -m unittest discover -s backend/tests
```

Beklenen: tüm testler pass; DSN-gated skip'ler ayrıca raporlanır.

- [x] **Adım 2: Frontend Node testlerini çalıştır**

```powershell
node --test frontend/app/*.test.cjs
```

Beklenen: tüm frontend testleri pass.

- [x] **Adım 3: Production frontend build çalıştır**

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
```

Beklenen: Next.js production build exit `0`.

- [x] **Adım 4: Compose ve shell kanıtlarını yeniden çalıştır**

```powershell
docker compose --profile backup --env-file deploy/production.env.example -f docker-compose.production.yml config --quiet
docker compose --env-file deploy/production.env.example -f docker-compose.production.yml config --services
docker compose --profile backup --env-file deploy/production.env.example -f docker-compose.production.yml config --services
docker compose --profile backup --env-file deploy/production.env.example -f docker-compose.production.yml run --rm --entrypoint sh backup -n /usr/local/bin/fisora-backup.sh
```

Beklenen: config ve syntax kontrolleri pass; profile'sız service listesinde
backup bulunmaz.

- [x] **Adım 5: Sentetik encrypted checkpoint ve scheduled restore kanıtını çalıştır**

Sentetik fixture ile iki mode'u üret, decrypt et ve ayrı PostgreSQL/root'a
restore et. Checkpoint'te document archive olmadığını, scheduled package'ta PDF
ve XML byte'larının bire bir eşleştiğini ve receipt digest'lerinin doğru
olduğunu raporla. Gerçek belge, secret veya production DSN kullanma.

- [x] **Adım 6: Diff bütünlüğünü doğrula**

```powershell
git diff --check
git status --short
git diff --stat
```

Beklenen: unrelated kullanıcı dosyaları korunur; yalnız bu plan kapsamındaki
tracked değişiklikler ve yeni spec/plan görünür.

- [x] **Adım 7: Release sınırında dur**

Kullanıcıya şu kanıtları tek preflight olarak sun:

- exact file scope;
- branch ve remote;
- backend/frontend/build/Compose/synthetic restore sonuçları;
- canlı hedef `codex@185.184.208.188`, checkout `/opt/fisora/app`;
- deploy ile backup container'ın `disabled` moda geçip duracağı;
- mevcut dump cleanup'ının kapsam dışı ve ayrı onay olduğu;
- material risk ve rollback.

Bu noktada `commit + push + deploy` için tek açık onay iste. Onay gelmeden stage,
commit, push, deploy, container stop veya dosya silme yapma.
