# Current Handoff

Bu dosya, Fisora kapali server demo calismasina baska bilgisayardan veya baska
oturumdan devam etmek icin son durumu ozetler.

## Son Durum

- Repo: `keremerdogdu92/Fisora`
- Aktif branch: `codex/bank-statement-review-engine`
- Son runtime deploy commit: `7be7055`
- Server repo dizini: `/opt/fisora/app`
- Server runtime: Docker Compose production stack
- Demo provider: Groq
- Server env dosyasi: `/opt/fisora/app/deploy/production.env`

`deploy/production.env` GitHub'a girmez. `POSTGRES_PASSWORD` ve `GROQ_API_KEY`
sadece serverdaki bu dosyada tutulur.

## Yeni Bilgisayarda Devam Etme

GitHub hesabi private repoya yetkili olmalidir. Son branch'i almak icin:

```bash
git clone -b codex/bank-statement-review-engine https://github.com/keremerdogdu92/Fisora.git
cd Fisora
```

Zaten clone varsa:

```bash
git fetch origin
git checkout codex/bank-statement-review-engine
git pull --ff-only
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
git checkout codex/bank-statement-review-engine
git pull --ff-only
```

Config kontrolu ve deploy:

```bash
sh deploy/scripts/fisora-prod.sh check
sh deploy/scripts/fisora-prod.sh deploy
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
FISORA_AI_MODEL=openai/gpt-oss-20b
FISORA_AI_COMPARISON_MODEL=openai/gpt-oss-120b
FISORA_AI_MONTHLY_CAP_USD=0.01
GROQ_API_KEY=<groq-key>
OPENAI_API_KEY=
```

Key'i gostermeden kontrol:

```bash
grep -E 'FISORA_AUTH_MODE|FISORA_AI_PROVIDER|FISORA_AI_MODEL|FISORA_AI_COMPARISON_MODEL' deploy/production.env
grep -q '^GROQ_API_KEY=.' deploy/production.env && echo "GROQ key var" || echo "GROQ key eksik"
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
ai_provider: groq
ai_model: openai/gpt-oss-20b
ai_groq_key_present: true
```

`zirve_verified_adapter_missing` warning'i normaldir. Zirve export sahada
mustavirle test edilmeden adapter verified sayilmaz.

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

1. Serverda `git pull --ff-only` ile `7be7055` veya daha yeni commit'i cek.
2. `sh deploy/scripts/fisora-prod.sh deploy` calistir.
3. Auth status `mock_header_required` donuyor mu kontrol et.
4. Readiness icinde `pilot_sellable=true`, `ai_groq_key_present=true` ve `ai_provider_configured=true`
   mi kontrol et.
5. Tarayicida `http://<SERVER_IP>/` ac.
6. Fatura ve banka upload akisini Groq AI acik halde dene.
7. Smoke failed kalirsa yukaridaki SQL komutuyla job error detayini al.
