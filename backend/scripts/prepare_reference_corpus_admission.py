from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SUPPORTED_DOCUMENT_TYPES = {"invoice", "einvoice_xml"}
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_source_path(source_root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or not relative_path.strip():
        raise ValueError("relative_path_must_stay_inside_source_root")
    root = source_root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("relative_path_must_stay_inside_source_root") from exc
    if not resolved.is_file():
        raise ValueError("manifest_source_file_missing")
    return resolved


def validate_manifest(*, manifest: dict[str, Any], source_root: Path) -> dict[str, Any]:
    if manifest.get("corpus_key") != "pilot-accountant-reference" or manifest.get("version") != 1:
        raise ValueError("invalid_reference_corpus_identity")
    items = manifest.get("items")
    if not isinstance(items, list) or len(items) != 50:
        raise ValueError("reference_corpus_requires_exactly_50_items")
    hashes: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("reference_corpus_item_must_be_object")
        relative_path = str(item.get("relative_path") or "").strip()
        client_id = str(item.get("client_id") or "").strip()
        period = str(item.get("period") or "").strip()
        direction = str(item.get("direction") or "").strip().lower()
        document_type = str(item.get("document_type") or "").strip()
        source_hash = str(item.get("sha256") or "").strip().lower()
        if not client_id or not PERIOD_RE.fullmatch(period):
            raise ValueError("reference_corpus_item_requires_client_and_period")
        if direction not in {"purchase", "sales"}:
            raise ValueError("reference_corpus_item_direction_invalid")
        if document_type not in SUPPORTED_DOCUMENT_TYPES:
            raise ValueError("reference_corpus_item_document_type_invalid")
        if not SHA256_RE.fullmatch(source_hash) or source_hash in hashes:
            raise ValueError("reference_corpus_item_hash_invalid_or_duplicate")
        path = _safe_source_path(source_root, relative_path)
        actual_hash = _sha256(path)
        if actual_hash != source_hash:
            raise ValueError("reference_corpus_item_hash_mismatch")
        hashes.add(source_hash)
        validated.append(
            {
                "relative_path": relative_path,
                "client_id": client_id,
                "period": period,
                "direction": direction,
                "document_type": document_type,
                "sha256": source_hash,
                "size_bytes": path.stat().st_size,
            }
        )
    purchase_count = sum(item["direction"] == "purchase" for item in validated)
    sales_count = sum(item["direction"] == "sales" for item in validated)
    if purchase_count != 35 or sales_count != 15:
        raise ValueError("reference_corpus_requires_35_purchase_and_15_sales")
    return {
        "corpus_key": "pilot-accountant-reference",
        "version": 1,
        "item_count": len(validated),
        "purchase_count": purchase_count,
        "sales_count": sales_count,
        "unique_sha256_count": len(hashes),
        "items": validated,
    }


def preflight(*, manifest_path: Path, source_root: Path, output_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = validate_manifest(manifest=manifest, source_root=source_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight a private 50-invoice accountant reference manifest without storing data.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = preflight(
            manifest_path=Path(args.manifest),
            source_root=Path(args.source_root),
            output_path=Path(args.output),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"reference corpus preflight failed: {exc}")
        return 1
    print(json.dumps({key: value for key, value in summary.items() if key != "items"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
