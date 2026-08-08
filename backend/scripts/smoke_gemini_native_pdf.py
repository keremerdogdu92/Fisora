from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.canonical_invoices import CanonicalExtractionRequest, canonical_invoice_from_ai_payload  # noqa: E402
from app.domain.openai_provider import DEFAULT_GEMINI_MODEL, GeminiAccountingProvider  # noqa: E402


def _synthetic_invoice_pdf() -> bytes:
    lines = [
        "SENTETIK TEST FATURASI",
        "FATURA NO: TEST2026000000001",
        "SATICI VKN: 1111111111",
        "ALICI VKN: 2222222222",
        "TEST HIZMETI 100.00 TL KDV %20 20.00 TL",
        "ODENECEK TOPLAM: 120.00 TL",
    ]
    operators: list[str] = []
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        move = "50 760 Td" if index == 0 else "0 -16 Td"
        operators.append(f"{move} ({escaped}) Tj")
    stream = f"BT /F1 10 Tf {' '.join(operators)} ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for item in objects:
        offsets.append(len(payload))
        payload.extend(item)
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(payload)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run_smoke(*, env: Mapping[str, str]) -> dict[str, object]:
    api_key = str(env.get("GEMINI_API_KEY") or "").strip()
    model = str(env.get("FISORA_GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    if not api_key:
        return {
            "status": "BLOCKED_MISSING_GEMINI_API_KEY",
            "provider": "gemini",
            "model": model,
            "schema_valid": False,
        }

    pdf_bytes = _synthetic_invoice_pdf()
    provider = GeminiAccountingProvider(
        api_key=api_key,
        model=model,
        generate_content_url=str(env.get("FISORA_GEMINI_GENERATE_CONTENT_URL") or ""),
        timeout_seconds=float(env.get("FISORA_GEMINI_TIMEOUT_SECONDS") or "60"),
        max_output_tokens=int(env.get("FISORA_GEMINI_MAX_OUTPUT_TOKENS") or "16384"),
        max_inline_pdf_bytes=int(env.get("FISORA_GEMINI_MAX_INLINE_PDF_BYTES") or "50000000"),
    )
    started = perf_counter()
    try:
        payload = provider.extract_invoice_canonical(
            CanonicalExtractionRequest(
                document_text="",
                document_bytes=pdf_bytes,
                document_mime_type="application/pdf",
                deterministic_payload={
                    "validation_status": "invalid",
                    "validation_reason_codes": ["line_items_missing"],
                    "line_items": [],
                },
                client_identity={"title": "SENTETIK TEST ALICISI", "tax_id": "2222222222"},
                mode="discovery",
            )
        )
        canonical_invoice_from_ai_payload(payload)
    except Exception as exc:  # noqa: BLE001 - smoke reports only safe error category
        return {
            "status": "FAILED",
            "provider": "gemini",
            "model": model,
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            "pdf_bytes": len(pdf_bytes),
            "schema_valid": False,
            "error_type": type(exc).__name__,
        }
    return {
        "status": "OK_SCHEMA_VALID",
        "provider": "gemini",
        "model": model,
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        "pdf_bytes": len(pdf_bytes),
        "schema_valid": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a secret-safe Gemini native-PDF synthetic smoke.")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy" / "production.env")
    args = parser.parse_args()
    env = {**os.environ, **_load_env_file(args.env_file)}
    result = run_smoke(env=env)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "OK_SCHEMA_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
