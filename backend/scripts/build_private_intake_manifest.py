from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "private_samples"
SUPPORTED_EXTENSIONS = {".pdf", ".xml", ".csv", ".xlsx", ".xls", ".json", ".zip"}
MANIFEST_COLUMNS = [
    "client_id",
    "client_name",
    "period",
    "privacy_level",
    "relative_path",
    "file_name",
    "extension",
    "document_kind",
    "size_bytes",
    "sha256",
    "notes",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_document_kind(path: Path) -> str:
    lower_name = path.name.lower()
    parts = " ".join(part.lower() for part in path.parts)
    if "zirve" in lower_name and ("import" in lower_name or "aktar" in lower_name):
        return "zirve_import_sample"
    if "hesap" in lower_name or "chart" in lower_name or "plan" in lower_name:
        return "chart_accounts"
    if "cari" in lower_name or "counterparty" in lower_name or "120" in lower_name or "320" in lower_name:
        return "counterparty_list"
    if "yevmiye" in lower_name or "muavin" in lower_name or "journal" in lower_name:
        return "journal_history"
    if "banka" in lower_name or "bank" in lower_name or "ekstre" in lower_name or "statement" in lower_name:
        return "bank_statement"
    if "pos" in lower_name or "pos" in parts:
        return "pos_statement"
    if path.suffix.lower() in {".pdf", ".xml", ".json"}:
        return "invoice"
    if path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
        return "spreadsheet_unknown"
    if path.suffix.lower() == ".zip":
        return "archive"
    return "unknown"


def build_manifest_rows(
    *,
    input_dir: Path,
    client_id: str,
    client_name: str,
    period: str,
    privacy_level: str,
) -> list[dict[str, object]]:
    files = [
        path
        for path in sorted(input_dir.rglob("*"), key=lambda item: str(item.relative_to(input_dir)).lower())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    rows = []
    for path in files:
        relative_path = str(path.relative_to(input_dir)).replace("\\", "/")
        rows.append(
            {
                "client_id": client_id,
                "client_name": client_name,
                "period": period,
                "privacy_level": privacy_level,
                "relative_path": relative_path,
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "document_kind": infer_document_kind(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "notes": "",
            }
        )
    return rows


def write_manifest_csv(rows: list[dict[str, object]], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def write_manifest_json(rows: list[dict[str, object]], output_path: Path, *, input_dir: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now(),
        "source_dir": str(input_dir),
        "file_count": len(rows),
        "document_kind_counts": {
            kind: sum(1 for row in rows if row["document_kind"] == kind)
            for kind in sorted({str(row["document_kind"]) for row in rows})
        },
        "files": rows,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a private intake manifest for real accountant/pilot files.")
    parser.add_argument("input_dir", help="Folder containing private pilot files.")
    parser.add_argument("--client-id", required=True, help="Fisora client id to attach these files to.")
    parser.add_argument("--client-name", default="", help="Human readable client name.")
    parser.add_argument("--period", default="", help="Period label, for example 2026-05.")
    parser.add_argument(
        "--privacy-level",
        choices=("real", "anonymized", "synthetic"),
        default="real",
        help="Privacy level of the source files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output folder ignored by git. Defaults to private_samples.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input folder not found: {input_dir}")

    output_dir = Path(args.output_dir)
    rows = build_manifest_rows(
        input_dir=input_dir,
        client_id=args.client_id,
        client_name=args.client_name or args.client_id,
        period=args.period,
        privacy_level=args.privacy_level,
    )
    csv_path = write_manifest_csv(rows, output_dir / "intake_manifest.csv")
    json_path = write_manifest_json(rows, output_dir / "intake_manifest.json", input_dir=input_dir)
    kinds = {row["document_kind"] for row in rows}
    print(f"Manifest rows: {len(rows)}")
    print(f"Document kinds: {', '.join(sorted(kinds)) if kinds else 'none'}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
