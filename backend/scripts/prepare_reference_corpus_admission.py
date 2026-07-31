from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _party_tax_ids(root: ET.Element, party_name: str) -> set[str]:
    party = next((element for element in root.iter() if _local_name(element.tag) == party_name), None)
    if party is None:
        return set()
    return {
        text
        for element in party.iter()
        if _local_name(element.tag) in {"CompanyID", "ID"}
        and (text := re.sub(r"\D", "", str(element.text or "")))
        and len(text) in {10, 11}
    }


def _xml_direction_matches(*, path: Path, direction: str, client_tax_id: str) -> bool:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError("reference_corpus_xml_party_evidence_invalid") from exc
    supplier_ids = _party_tax_ids(root, "AccountingSupplierParty")
    customer_ids = _party_tax_ids(root, "AccountingCustomerParty")
    expected_ids, opposite_ids = (
        (customer_ids, supplier_ids)
        if direction == "purchase"
        else (supplier_ids, customer_ids)
    )
    return client_tax_id in expected_ids and client_tax_id not in opposite_ids


def build_corrected_manifest(*, manifest: dict[str, Any], source_root: Path) -> dict[str, Any]:
    corrected = json.loads(json.dumps(manifest))
    items = corrected.get("items")
    if not isinstance(items, list):
        raise ValueError("reference_corpus_items_missing")
    xml_identity_candidates: dict[str, list[set[str]]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("reference_corpus_item_must_be_object")
        direction = str(item.get("direction") or "").strip().lower()
        if direction not in {"purchase", "sales"}:
            raise ValueError("reference_corpus_item_direction_invalid")
        item["intake_category"] = f"{direction}_invoice"
        path = _safe_source_path(source_root, str(item.get("relative_path") or "").strip())
        if path.suffix.lower() != ".xml":
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise ValueError("reference_corpus_xml_party_evidence_invalid") from exc
        expected_ids = (
            _party_tax_ids(root, "AccountingCustomerParty")
            if direction == "purchase"
            else _party_tax_ids(root, "AccountingSupplierParty")
        )
        if not expected_ids:
            raise ValueError("reference_corpus_xml_party_evidence_missing")
        client_id = str(item.get("client_id") or "").strip()
        xml_identity_candidates.setdefault(client_id, []).append(expected_ids)
    inferred_identities: dict[str, str] = {}
    for client_id, candidates in xml_identity_candidates.items():
        common = set.intersection(*candidates)
        if len(common) != 1:
            raise ValueError("reference_corpus_xml_client_identity_ambiguous")
        inferred_identities[client_id] = next(iter(common))
    for item in items:
        client_id = str(item.get("client_id") or "").strip()
        if client_id in inferred_identities:
            item["client_tax_id"] = inferred_identities[client_id]
    return corrected


def write_intake_manifests(
    *,
    manifest: dict[str, Any],
    source_root: Path,
    output_dir: Path,
) -> dict[str, Path]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in manifest.get("items") or []:
        client_id = str(item.get("client_id") or "").strip()
        grouped.setdefault(client_id, []).append(item)
    written: dict[str, Path] = {}
    for client_id, items in grouped.items():
        chart_dir = source_root / client_id / "chart_accounts"
        chart_files = sorted(
            path
            for path in chart_dir.glob("*")
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".xls"}
        )
        if len(chart_files) != 1:
            raise ValueError("reference_corpus_requires_one_chart_file_per_client")
        chart_relative = chart_files[0].resolve().relative_to(source_root.resolve()).as_posix()
        rows = [
            {
                "relative_path": chart_relative,
                "file_name": chart_files[0].name,
                "extension": chart_files[0].suffix.lower(),
                "document_kind": "chart_accounts",
            }
        ]
        rows.extend(
            {
                "relative_path": str(item["relative_path"]),
                "file_name": Path(str(item["relative_path"])).name,
                "extension": Path(str(item["relative_path"])).suffix.lower(),
                "document_kind": "invoice",
                "intake_category": str(item["intake_category"]),
                "period": str(item["period"]),
                "sha256": str(item["sha256"]),
            }
            for item in items
        )
        payload = {
            "source_dir": str(source_root.resolve()),
            "client_id": client_id,
            "file_count": len(rows),
            "files": rows,
        }
        output_path = output_dir / f"{client_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written[client_id] = output_path
    return written


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
        client_tax_id = re.sub(r"\D", "", str(item.get("client_tax_id") or ""))
        period = str(item.get("period") or "").strip()
        direction = str(item.get("direction") or "").strip().lower()
        intake_category = str(item.get("intake_category") or "").strip().lower()
        document_type = str(item.get("document_type") or "").strip()
        source_hash = str(item.get("sha256") or "").strip().lower()
        if not client_id or not PERIOD_RE.fullmatch(period):
            raise ValueError("reference_corpus_item_requires_client_and_period")
        if direction not in {"purchase", "sales"}:
            raise ValueError("reference_corpus_item_direction_invalid")
        if intake_category != f"{direction}_invoice":
            raise ValueError("reference_corpus_item_intake_category_invalid")
        if document_type not in SUPPORTED_DOCUMENT_TYPES:
            raise ValueError("reference_corpus_item_document_type_invalid")
        if not SHA256_RE.fullmatch(source_hash) or source_hash in hashes:
            raise ValueError("reference_corpus_item_hash_invalid_or_duplicate")
        path = _safe_source_path(source_root, relative_path)
        actual_hash = _sha256(path)
        if actual_hash != source_hash:
            raise ValueError("reference_corpus_item_hash_mismatch")
        if path.suffix.lower() == ".xml":
            if len(client_tax_id) not in {10, 11}:
                raise ValueError("reference_corpus_xml_client_tax_id_required")
            if not _xml_direction_matches(
                path=path,
                direction=direction,
                client_tax_id=client_tax_id,
            ):
                raise ValueError("reference_corpus_xml_party_direction_conflict")
        hashes.add(source_hash)
        validated.append(
            {
                "relative_path": relative_path,
                "client_id": client_id,
                "period": period,
                "direction": direction,
                "intake_category": intake_category,
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
        "missing_direction_count": 0,
        "duplicate_source_hash_count": 0,
        "xml_party_direction_conflict_count": 0,
        "items": validated,
    }


def preflight(
    *,
    manifest_path: Path,
    source_root: Path,
    output_path: Path,
    corrected_manifest_path: Path | None = None,
    intake_manifest_dir: Path | None = None,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corrected_manifest_path is not None:
        manifest = build_corrected_manifest(manifest=manifest, source_root=source_root)
    summary = validate_manifest(manifest=manifest, source_root=source_root)
    if intake_manifest_dir is not None:
        write_intake_manifests(
            manifest=manifest,
            source_root=source_root,
            output_dir=intake_manifest_dir,
        )
    if corrected_manifest_path is not None:
        corrected_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        corrected_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight a private 50-invoice accountant reference manifest without storing data.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--corrected-manifest-output")
    parser.add_argument("--intake-manifest-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = preflight(
            manifest_path=Path(args.manifest),
            source_root=Path(args.source_root),
            output_path=Path(args.output),
            corrected_manifest_path=(
                Path(args.corrected_manifest_output)
                if args.corrected_manifest_output
                else None
            ),
            intake_manifest_dir=(
                Path(args.intake_manifest_dir)
                if args.intake_manifest_dir
                else None
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"reference corpus preflight failed: {exc}")
        return 1
    print(json.dumps({key: value for key, value in summary.items() if key != "items"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
