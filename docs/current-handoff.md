# Current Handoff

Bu dosya, Fisora kapali server demo calismasina baska bilgisayardan veya baska
oturumdan devam etmek icin son durumu ozetler.

## Son Durum

- Repo: `keremerdogdu92/Fisora`
- Aktif branch: `main`
- Son dogrulanan runtime deploy: `main` ucu; deploy sonunda `git rev-parse`
  ile tekrar kontrol edilir.
- Son deploy smoke: 2026-06-23, `/health` 200, readiness `ready=true`,
  `pilot_sellable=true`, root route 200.
- Server repo dizini: `/opt/fisora/app`
- Server runtime: Docker Compose production stack
- Demo provider: Groq
- AI fallback kodu: `FISORA_AI_PROVIDER_CHAIN=groq,openrouter,cerebras`
  destekli. Keyler sadece serverdaki ignored `deploy/production.env` dosyasinda
  tutulur.
- Faz 3 Tavily Bilgi Havuzu pilot akisi hazirlandi. Otomatik research sadece
  belirsiz faturalarda calisir; OpenAI web research sonraki iterasyon icin
  kodda korunur. Tavily icin `FISORA_RESEARCH_ENABLED=true`,
  `FISORA_RESEARCH_PROVIDER=tavily` ve `TAVILY_API_KEY` gerekir. Bilgi Havuzu
  route'u: `/portal/bilgi-havuzu`.
- Server env dosyasi: `/opt/fisora/app/deploy/production.env`

`deploy/production.env` GitHub'a girmez. `POSTGRES_PASSWORD`, `GROQ_API_KEY`,
`OPENROUTER_API_KEY`, `CEREBRAS_API_KEY` ve varsa fallback provider keyleri
sadece serverdaki bu dosyada tutulur.

## Yeni Bilgisayarda Devam Etme

GitHub hesabi private repoya yetkili olmalidir. Aktif pilot branch'ini almak icin:

```bash
git clone -b main https://github.com/keremerdogdu92/Fisora.git
cd Fisora
```

Zaten clone varsa:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

## Serverda Kaldigimiz Yer

Serverda Docker kuruldu ve stack bir kez basariyla ayaga kalkti. Su servisler
healthy gorundu:

- `backend`
- `frontend`
- `postgres`
- `redis`
- `nginx`

Nginx `80` portunu disari aciyor. Tarayicida demo URL formati:

```text
http://<SERVER_IP>/
```

`<SERVER_IP>` degeri repoya yazilmaz; server panelinden veya mevcut SSH
bilgisinden bakilir.

## Serverda Son Kodu Cekme ve Redeploy

Serverda son commit'i almak icin:

```bash
cd /opt/fisora/app
git fetch origin
git checkout main
git pull --ff-only origin main
```

Config kontrolu ve deploy:

```bash
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1 -Branch main -BaseUrl http://185.184.208.188 -SkipLocalVerify -Json
```

## Env Kontrolu

Serverdaki asil env dosyasi:

```bash
nano /opt/fisora/app/deploy/production.env
```

Minimum beklenen satirlar:

```env
POSTGRES_PASSWORD=<strong-password>
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
FISORA_RESEARCH_ENABLED=true
FISORA_RESEARCH_PROVIDER=tavily
FISORA_RESEARCH_MODEL=gpt-5.4-mini
FISORA_RESEARCH_MAX_PER_DOCUMENT=1
FISORA_RESEARCH_CONFIDENCE_THRESHOLD=70
GROQ_API_KEY=<groq-key>
OPENROUTER_API_KEY=<rotated-openrouter-key>
CEREBRAS_API_KEY=<cerebras-key>
OPENAI_API_KEY=
TAVILY_API_KEY=<tavily-key>
```

Key'i gostermeden kontrol:

```bash
grep -E 'FISORA_AUTH_MODE|FISORA_AI_PROVIDER|FISORA_AI_PROVIDER_CHAIN|FISORA_AI_MODEL|FISORA_(GROQ|OPENROUTER|CEREBRAS)_MODEL|FISORA_AI_COMPARISON_MODEL' deploy/production.env
grep -q '^GROQ_API_KEY=.' deploy/production.env && echo "GROQ key var" || echo "GROQ key eksik"
grep -q '^OPENROUTER_API_KEY=.' deploy/production.env && echo "OpenRouter key var" || echo "OpenRouter key eksik"
grep -q '^CEREBRAS_API_KEY=.' deploy/production.env && echo "Cerebras key var" || echo "Cerebras key eksik"
```

## Beklenen Health ve Readiness

Server icinden:

```bash
curl -i http://127.0.0.1/health
curl -s http://127.0.0.1/api/phase0/store/auth/status
curl -s http://127.0.0.1/api/phase0/store/system/readiness
```

Beklenen kritik degerler:

```text
health: 200 OK
auth_mode: mock_header_required
ready: true
pilot_sellable: true
production_ready: false
ai_provider: groq
ai_model: openai/gpt-oss-20b
ai_groq_key_present: true
zirve_mapping_adapter_available: true
rate_limit_configured: true
```

`zirve_verified_adapter_missing`, `zirve_field_test_pending` ve
`session_required_missing` warning'leri kapali demo modunda normaldir. Zirve
export sahada mustavirle test edilmeden adapter verified sayilmaz; canlı demo
`mock_header_required` modunda kaldigi surece `production_ready=false` kalir.

## Smoke Durumu

`sh deploy/scripts/fisora-prod.sh smoke` bir kez `failed_count=1` verdi. Bu
backend/frontend/nginx'in ayakta olmadigi anlamina gelmiyor; health kontrolleri
basariliydi. Redeploy sonrasi tekrar bak:

```bash
sh deploy/scripts/fisora-prod.sh smoke
```

Yine failed donerse hata detayini al:

```bash
docker compose --env-file deploy/production.env -f docker-compose.production.yml -p fisora exec postgres psql -U fisora -d fisora -c "select payload->>'status' as status, payload->>'error_message' as error_message, payload from workflow_records where record_type='processing_job' order by updated_at desc limit 5;"
```

## Guvenlik Notlari

- Groq key, GitHub token, SSH private key ve server root sifresi chat'e veya
  repoya yazilmaz.
- Server internete acik oldugu anda bot taramalari gelir; nginx logunda
  bilinmeyen 404 istekleri normaldir ama firewall/IP kisiti planlanmalidir.
- Demo kapali IP ile yapilacaksa once SSH ve HTTP erisimi kimlerle paylasilacak
  netlestirilmelidir.

## Kaldigimiz Pratik Sira

1. Serverda `git checkout main && git pull --ff-only origin main` ile son commit'i cek.
2. `sh deploy/scripts/fisora-prod.sh check && sh deploy/scripts/fisora-prod.sh deploy && sh deploy/scripts/fisora-prod.sh smoke` calistir.
3. Auth status `mock_header_required` donuyor mu kontrol et.
4. Readiness icinde `pilot_sellable=true`, `production_ready=false`,
   `zirve_mapping_adapter_available=true`, `rate_limit_configured=true`,
   `ai_groq_key_present=true` ve `ai_provider_configured=true` mi kontrol et.
5. Tarayicida `http://<SERVER_IP>/` ac.
6. Fatura ve banka upload akisini Groq AI acik halde dene.
7. Smoke failed kalirsa yukaridaki SQL komutuyla job error detayini al.
