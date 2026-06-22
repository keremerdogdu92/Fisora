# Production Deploy Checklist

Bu liste yerel Docker smoke testinden sonra gercek Turkiye lokasyonlu sunucuya
gecis icin kullanilir.

## 1. Sunucu Hazirligi

- Ubuntu LTS kurulumu tamamlandi.
- SSH sadece key ile acik.
- Root login kapali.
- Firewall: 22, 80, 443 disinda port kapali.
- Docker Engine ve Docker Compose kurulu.
- Sunucu saat dilimi ve NTP dogru.
- Disk buyutme ve paket buyutme proseduru saglayicidan yazili alindi.

## 2. Dizin ve Volume

```text
/opt/fisora/app
/opt/fisora/data/documents
/opt/fisora/data/exports
/opt/fisora/data/backups
/opt/fisora/logs
```

- Belge volume'u sifreleme karari net.
- Backup hedefi ayni makine disinda olacak sekilde planlandi.
- Ham belgeler database'e yazilmiyor; sadece path/hash/metaveri tutuluyor.

## 3. Env ve Secret

- `POSTGRES_PASSWORD` production secret ile degisti.
- `FISORA_AUTH_MODE=trusted_header` sadece gateway dogrulanmis user id
  enjekte ediyorsa kullaniliyor.
- Gateway hazir degilse canliya alinmaz; pilot demo icin
  `mock_header_required` ve kapali erisim tercih edilir.
- Mustavir oncesi kapali server demo icin `FISORA_AI_PROVIDER=groq` kullanilir.
- `GROQ_API_KEY` sadece server env dosyasina yazilir; GitHub'a veya koda
  eklenmez.
- `FISORA_AI_MODEL=openai/gpt-oss-20b`, karsilastirma icin
  `FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b` ayarlanir.
- Ilk Groq demo cap'i uygulama ledger'inda `FISORA_AI_MONTHLY_CAP_USD=0.01`
  olarak tutulur; asil sinir Groq console free-tier/rate-limit kurallaridir.
- Ucretli OpenAI kalite kiyasi ayrica istenirse `FISORA_AI_PROVIDER=openai`,
  `OPENAI_API_KEY` ve OpenAI billing cap ile acilir.
- Faz 3 pilot research icin `FISORA_RESEARCH_ENABLED=true`,
  `FISORA_RESEARCH_PROVIDER=tavily`, `FISORA_RESEARCH_MAX_PER_DOCUMENT=1`,
  `FISORA_RESEARCH_CONFIDENCE_THRESHOLD=70` ve server env dosyasinda
  `TAVILY_API_KEY` gerekir. OpenAI research sonraki iterasyona birakilir.
- `FISORA_BACKUP_PATH=/opt/fisora/data/backups`.

## 4. TLS ve Nginx

- Domain DNS'i sunucuya yonlenir.
- Let's Encrypt sertifikasi alinir.
- HTTP -> HTTPS redirect acilir.
- Upload body size limiti fatura/ekstre hacmine gore ayarlanir.
- Auth header guvenligi icin tarayicidan gelen `X-Fisora-User-Id` silinir;
  dogrulanmis session varsa backend'e yeniden eklenir.

## 5. Ilk Smoke Komutlari

```bash
sh deploy/scripts/fisora-prod.sh check
sh deploy/scripts/fisora-prod.sh deploy
sh deploy/scripts/fisora-prod.sh smoke
```

Kabul:

- Postgres ve Redis healthy.
- Migration runner basarili.
- Postgres smoke `status=ok`.
- `/health` 200.
- Frontend aciliyor.
- `/api/phase0/summary` 200.
- `/api/phase0/store/system/readiness` 200 ve `ready=true`.
- Readiness payload'inda `backup` ve `storage_usage` alanlari gorunur.

## 6. Worker, Export ve Backup Smoke

- Demo mukellef onboarding paketi API'den olusturulur.
- Atanmis kullaniciyla bir banka CSV veya fatura PDF yuklenir.
- Worker tek sefer kosulur:

```bash
docker compose --env-file deploy/production.env -f docker-compose.production.yml run --rm -e FISORA_WORKER_RUN_ONCE=1 worker
```

Kabul:

- Processing job `completed`.
- Workspace'te belge sonucu olustu.
- Risk yoksa export package olusur.
- CSV ve manifest indirilebilir.
- Backup tek sefer kosulur ve dump/manifest uretilir:

```bash
sh deploy/scripts/fisora-prod.sh backup-once
```

## 7. Canliya Almadan Once

- Gercek fatura ve ekstreler local/private ortamda test edildi.
- Ham belgelerin 90 gun retention davranisi dogrulandi.
- Mustavir review ekraninda export gate gerekceleri gorunuyor.
- Zirve import formati sahada test edilene kadar `verified_in_zirve=false`.
- Export dosyasi gercek Zirve testinden gecmeden musteriye kesin aktarim
  formati olarak sunulmuyor.
- `trusted_header` veya session auth akisi gercek kullanici icin test edildi.
