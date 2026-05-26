# Backend

Faz 0 backend'i iki katmandan olusur:

- FastAPI iskeleti: API yonunu sabitler.
- Saf Python domain modulleri: hesap plani importu, fis uretimi ve export
  prototiplerini frontend'den bagimsiz dogrular.

## Kurulum

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
