from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.invoice_edge_cases import summarize_invoice_edge_cases  # noqa: E402


MANIFEST_COLUMNS = [
    "file_name",
    "extension",
    "size_bytes",
    "sha256",
    "page_count",
    "text_extractable",
    "extracted_char_count",
    "provider_hint",
    "invoice_no",
    "ettn",
    "detected_keywords",
    "risk_flags",
    "suggested_expected_behavior",
    "notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_text(path: Path) -> tuple[int, str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return 0, "", "pypdf_not_installed"

    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return len(reader.pages), "\n".join(chunks), ""
    except Exception as exc:  # noqa: BLE001
        return 0, "", f"pdf_read_error:{type(exc).__name__}"


def scan_file(path: Path) -> dict[str, object]:
    page_count = 0
    text = ""
    notes = ""

    if path.suffix.lower() == ".pdf":
        page_count, text, notes = extract_pdf_text(path)
    else:
        notes = "unsupported_for_text_extraction"

    summary = summarize_invoice_edge_cases(path.name, text, extracted_char_count=len(text.strip()))
    return {
        "file_name": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "page_count": page_count,
        "text_extractable": "yes" if len(text.strip()) >= 100 else "no",
        "extracted_char_count": len(text.strip()),
        "provider_hint": summary.provider_hint,
        "invoice_no": summary.invoice_no,
        "ettn": summary.ettn,
        "detected_keywords": ";".join(summary.detected_keywords),
        "risk_flags": ";".join(summary.risk_flags),
        "suggested_expected_behavior": summary.suggested_expected_behavior,
        "notes": notes,
    }


def scan_folder(input_dir: Path, output_path: Path) -> list[dict[str, object]]:
    files = sorted([path for path in input_dir.rglob("*") if path.is_file()], key=lambda item: item.name.lower())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [scan_file(path) for path in files]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan private invoice samples and write a local manifest.")
    parser.add_argument("input_dir", help="Folder containing private invoice samples.")
    parser.add_argument(
        "--output",
        default=str(ROOT / "private_samples" / "manifest.csv"),
        help="Output CSV path. Defaults to private_samples/manifest.csv.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input folder not found: {input_dir}")

    rows = scan_folder(input_dir, Path(args.output))
    review_count = sum(1 for row in rows if row["suggested_expected_behavior"] == "review_queue")
    print(f"Scanned {len(rows)} files. Review queue candidates: {review_count}. Manifest: {args.output}")


if __name__ == "__main__":
    main()

