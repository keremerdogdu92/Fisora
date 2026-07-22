import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

def load_env():
    env_path = ROOT / "deploy" / "production.env"
    if not env_path.exists():
        print("production.env not found!")
        return
    with open(env_path, "r", encoding="utf-16") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip()
                if key.startswith("\ufeff"):
                    key = key.replace("\ufeff", "")
                key = "".join(c for c in key if ord(c) < 128)
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                os.environ[key] = val
                print(f"Loaded: {key} (val_len={len(val)})")

def run_benchmark():
    load_env()
    script_path = BACKEND / "scripts" / "run_private_pipeline_benchmark.py"
    cmd = [sys.executable, str(script_path), "--include-ai", "--firm", "firma-1"]
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    print("STDOU:")
    print(result.stdout)
    print("STDERR:")
    print(result.stderr)

if __name__ == "__main__":
    run_benchmark()