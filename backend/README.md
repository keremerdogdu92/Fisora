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
