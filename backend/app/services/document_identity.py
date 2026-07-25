from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import xml.etree.ElementTree as ET


MAX_IDENTITY_XML_BYTES = 10 * 1024 * 1024


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(root: ET.Element, name: str) -> str:
    for element in root.iter():
        if _local_name(element.tag) == name and str(element.text or "").strip():
            return str(element.text).strip()
    return ""


def _first_text_under(root: ET.Element, parent_name: str, child_name: str) -> str:
    for parent in root.iter():
        if _local_name(parent.tag) != parent_name:
            continue
        return _first_text(parent, child_name)
    return ""


def _normalized_amount(value: str) -> str:
    try:
        return format(Decimal(value.strip()), "f")
    except (InvalidOperation, ValueError):
        return ""


def extract_source_identities(
    *,
    content: bytes | None,
    file_name: str,
) -> list[dict[str, str]]:
    if not content or Path(file_name).suffix.lower() != ".xml":
        return []
    if len(content) > MAX_IDENTITY_XML_BYTES:
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    identities: list[dict[str, str]] = []
    ettn = _first_text(root, "UUID")
    if ettn:
        identities.append({"kind": "ettn", "value": ettn})

    invoice_no = _first_text(root, "ID")
    issue_date = _first_text(root, "IssueDate")
    payable_total = _normalized_amount(_first_text(root, "PayableAmount"))
    issuer_tax_id = _first_text_under(root, "AccountingSupplierParty", "ID")
    if invoice_no and issue_date and payable_total and issuer_tax_id:
        identities.append(
            {
                "kind": "issuer_invoice",
                "value": "|".join(
                    (issuer_tax_id, invoice_no, issue_date, payable_total)
                ),
            }
        )
    return identities
