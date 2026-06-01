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
girmez.

## Yerel MVP Store

Phase 0 API, kalici demo snapshot'lari icin varsayilan olarak
`exports/phase0_store.json` dosyasini kullanir. `exports/` gitignored oldugu
icin bu dosyaya yazilan musteri/veri denemeleri repoya girmez.

Farkli bir store dosyasi kullanmak icin:

```powershell
$env:FISORA_STORE_PATH="C:\\tmp\\fisora-phase0-store.json"
```

Ilk PostgreSQL adapter'i eklenene kadar bu store su endpointlerin davranisini
yerel olarak dogrulamak icindir:

- `POST /phase0/store/client`
- `POST /phase0/store/chart-accounts`
- `POST /phase0/store/simulation`
- `POST /phase0/store/review-decision`
- `POST /phase0/store/export-package`
- `GET /phase0/store/workspace/{client_id}`

## AI Adapter Davranisi

Urun/kalem siniflandirma akisi maliyet kontrollu calisir:

1. Statik kural kutuphanesi once calisir.
2. Statik eslesme yeterince guvenliyse AI cagrilmaz.
3. AI kapaliysa veya provider bagli degilse sistem statik sonuc ile devam eder.
4. Provider baglandiginda sonuc kategori/guven/gerekce iceren JSON schema ile
   dogrulanir.

Ilk yerel endpoint:

- `POST /phase0/classification/product`

Simulation endpointleri `aiClassificationUsed`, `aiClassificationProvider`,
`aiClassificationSkippedReason`, `aiClassificationReason` ve
`aiEstimatedInputChars` alanlarini dondurur. Bu alanlar muhasebe kararini tek
basina vermez; sadece siniflandirma izini ve maliyet sinyalini tasir.
