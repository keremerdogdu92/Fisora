# File: backend/app/workflows/three_stage_accounting_pipeline.py
# Summary: Runs the source Reader, semantic planner, and planner-owned-counterparty accountant pipeline.
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

import httpx

from app.domain.chart_accounts import normalize_account_code

PIPELINE_VERSION = "source-identity-tax-accountant-v3"
READER_PROMPT_VERSION = "invoice-source-reader-v4"
PLANNER_PROMPT_VERSION = "invoice-identity-tax-resolver-v3"
ACCOUNTANT_PROMPT_VERSION = "identity-tax-accountant-v3"
SCHEMA_VERSION = "source-identity-tax-accountant-v3"
_ENABLED_VALUES = {"1", "true", "yes", "on"}
_CURRENT_ACCOUNT_PREFIXES = ("120", "220", "320", "329", "420")


def three_stage_accounting_enabled(env: Mapping[str, str]) -> bool:
    return str(env.get("FISORA_THREE_STAGE_ACCOUNTING_ENABLED") or "").strip().lower() in _ENABLED_VALUES


@dataclass(frozen=True)
class ThreeStageAccountingRun:
    result: dict[str, Any]
    source_package: dict[str, Any]
    source_text: str
    semantic_plan: dict[str, Any]
    final_output: dict[str, Any]
    reader_attempt: Any
    planner_attempt: Any
    stage_elapsed_ms: dict[str, int]
TEXT = {"type": "string"}
LABELED = {
    "type": "object",
    "properties": {"label": TEXT, "value": TEXT},
    "required": ["label", "value"],
    "additionalProperties": False,
}
PARTY = {
    "type": "object",
    "properties": {
        "heading": TEXT,
        "primary_name": TEXT,
        "detail_lines": {"type": "array", "items": LABELED},
    },
    "required": ["heading", "primary_name", "detail_lines"],
    "additionalProperties": False,
}
RAW_ROW = {
    "type": "object",
    "properties": {
        "source_position": TEXT,
        "source_text": TEXT,
        "description": TEXT,
        "ui_amount": TEXT,
        "ui_amount_label": TEXT,
        "ui_amount_basis": {"type": "string", "enum": ["line_total_ex_tax", "line_total_inc_tax", "ambiguous", "none"]},
        "ui_role": {"type": "string", "enum": ["posting_candidate", "group_or_subtotal", "informational"]},
    },
    "required": ["source_position", "source_text", "description", "ui_amount", "ui_amount_label", "ui_amount_basis", "ui_role"],
    "additionalProperties": False,
}
READER_SCHEMA = {
    "type": "object",
    "properties": {
        "document_header": {"type": "array", "items": LABELED},
        "principal_parties": {"type": "array", "items": PARTY, "maxItems": 2},
        "invoice_table_header": TEXT,
        "invoice_table_rows": {"type": "array", "items": RAW_ROW},
        "printed_summary_lines": {"type": "array", "items": LABELED},
        "note_lines": {"type": "array", "items": TEXT},
    },
    "required": ["document_header", "principal_parties", "invoice_table_header", "invoice_table_rows", "printed_summary_lines", "note_lines"],
    "additionalProperties": False,
}
READER_INSTRUCTIONS = (
    "Reconstruct the visible invoice as source text only. Do not make accounting decisions, classify monetary values, calculate, reconcile, normalize or correct the source. "
    "Preserve printed wording, labels, identifiers, quantities, rates, amounts, signs, decimal separators and currency. "
    "principal_parties must contain only the two principal invoice identity blocks. Keep each party's nearby name/title, address and labeled identifiers together. "
    "Never create a principal party from delivery/shipping address, carrier, branch, warehouse, salesperson, fleet, bank, payment provider or another operational block; preserve such text in note_lines instead. "
    "Do not decide which principal party is us, supplier, customer, buyer or seller unless that exact role heading is printed. Preserve only the printed heading. "
    "Copy the main invoice table header in visible column order. Copy every visibly presented row under that main table exactly once into invoice_table_rows. "
    "For each table row also prepare a source-only review projection: description must copy the visible goods/service/charge description without paraphrase; ui_amount must copy the row's visibly printed final billed amount/total cell without calculation; ui_amount_label must copy the corresponding visible column label when one exists. If no single final row amount is unambiguous, leave ui_amount and ui_amount_label empty. "
    "Set ui_amount_basis from visible layout only: line_total_ex_tax when the copied row total visibly excludes separately shown row/invoice tax, line_total_inc_tax when it visibly includes tax, ambiguous when the source does not make this safe to tell, and none when ui_amount is empty. Never calculate one basis from another. "
    "ui_role is document-structure only, not accounting: posting_candidate for a concrete non-zero goods/service/charge/discount row that a reviewer may work on; group_or_subtotal for a heading/roll-up/subtotal that summarizes or is broken down by other visible rows; informational for table notes and rows whose final billed amount is visibly zero because they are fully discounted, warranty/free components, or otherwise carry no current-invoice posting amount. Use visible hierarchy, indentation, repeated roll-up amounts and following detail rows to avoid double counting: when a category/roll-up row and its child/detail rows describe the same charge, mark the roll-up group_or_subtotal rather than marking both levels posting_candidate. Do not infer accounts, debit/credit, VAT treatment or accounting meaning from ui_role. "
    "Do not assign row values to accounting-semantic fields such as VAT treatment, expense/revenue account, debit/credit or posting basis; keep each row's source_text as the complete faithful evidence. "
    "Rows outside the main invoice table, including separately printed totals/taxes/fees/balances, belong in printed_summary_lines as exact label/value pairs. "
    "Preserve remaining visible notes, delivery, carrier, bank and payment statements in note_lines. "
    "document_header should contain only invoice/document identity facts: customization number, scenario, invoice type, invoice number/ID, invoice date/time and ETTN/UUID. "
    "Do not include service/package/account/order/route/payment/next-period fields in document_header; preserve them in note_lines if useful. "
    "Do not invent missing facts. Use empty arrays or empty strings when a section is not visible."
)

TAX_HINT = {
    "type": "object",
    "properties": {
        "label": TEXT,
        "semantic_type": {"type": "string", "enum": ["vat_input", "vat_output", "non_vat_tax", "other"]},
    },
    "required": ["label", "semantic_type"],
    "additionalProperties": False,
}
PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "accounting_direction": {"type": "string", "enum": ["purchase", "sales", "return", "unknown"]},
        "our_party_index": {"type": "string", "enum": ["1", "2", "unknown"]},
        "counterparty_name": TEXT,
        "counterparty_identifier": TEXT,
        "counterparty_match": {"type": "string", "enum": ["exact", "none", "uncertain"]},
        "counterparty_account_code": TEXT,
        "tax_components": {"type": "array", "items": TAX_HINT},
        "warnings": {"type": "array", "items": TEXT},
    },
    "required": ["accounting_direction", "our_party_index", "counterparty_name", "counterparty_identifier", "counterparty_match", "counterparty_account_code", "tax_components", "warnings"],
    "additionalProperties": False,
}
PLANNER_INSTRUCTIONS = (
    "Act only as the tenant-relative identity/current-account resolver plus a minimal tax-type classifier. Do not perform posting-basis, row, account-selection or journal interpretation. "
    "Use invoice source text as identity evidence and expected_direction as authoritative tenant-relative direction. Identify which principal party is the client and which is the counterparty. "
    "Return the counterparty title and tax identifier from the source. Choose a supplied counterparty candidate only on clear title or tax-identity match; otherwise return none and an empty account code. "
    "Never match a generic ALICILAR/SATICILAR account as a real counterparty identity. For each visibly printed tax label, return only its semantic type: purchase VAT=vat_input, sales VAT=vat_output, OIV/other non-VAT levies=non_vat_tax, otherwise other. "
    "Do not return tax amounts, posting basis, row plans, expense/revenue meaning, account families or journal amounts."
)

ROW_DECISION = {
    "type": "object",
    "properties": {
        "source_position": TEXT,
        "role": {"type": "string", "enum": ["business_line", "discount_or_reduction", "tax_or_fee", "subtotal_or_group", "non_posting_info", "uncertain"]},
        "account_code": TEXT,
        "reason": TEXT,
    },
    "required": ["source_position", "role", "account_code", "reason"],
    "additionalProperties": False,
}
JOURNAL_LINE = {
    "type": "object",
    "properties": {
        "account_code": TEXT,
        "account_name": TEXT,
        "description": TEXT,
        "debit": TEXT,
        "credit": TEXT,
        "source_positions": {"type": "array", "items": TEXT},
    },
    "required": ["account_code", "account_name", "description", "debit", "credit", "source_positions"],
    "additionalProperties": False,
}
COUNTERPARTY_POSTING = {
    "type": "object",
    "properties": {
        "description": TEXT,
        "debit": TEXT,
        "credit": TEXT,
        "source_positions": {"type": "array", "items": TEXT},
    },
    "required": ["description", "debit", "credit", "source_positions"],
    "additionalProperties": False,
}
ACCOUNTANT_SCHEMA = {
    "type": "object",
    "properties": {
        "accounting_direction": {"type": "string", "enum": ["purchase", "sales", "return", "unknown"]},
        "row_decisions": {"type": "array", "items": ROW_DECISION},
        "operating_journal_lines": {"type": "array", "items": JOURNAL_LINE},
        "counterparty_posting": COUNTERPARTY_POSTING,
        "posting_basis_label": TEXT,
        "posting_basis_amount": TEXT,
        "warnings": {"type": "array", "items": TEXT},
        "summary": TEXT,
    },
    "required": ["accounting_direction", "row_decisions", "operating_journal_lines", "counterparty_posting", "posting_basis_label", "posting_basis_amount", "warnings", "summary"],
    "additionalProperties": False,
}
ACCOUNTANT_INSTRUCTIONS = (
    "Act as the final accountant after an identity/current-account resolver. Source text is the factual and accounting-semantic authority; semantic_plan gives only tenant-relative direction, party identity, counterparty-account resolution and minimal tax-type hints. "
    "expected_direction is authoritative for tenant-relative accounting direction; issuer-side SATIS labels must not override it. Use client identity/activity as business context. "
    "Independently determine the current-invoice posting basis, row economic meaning, discounts, VAT/non-VAT taxes and journal amounts from the source text. posting_basis means the current invoice amount used for the balancing counterparty receivable/payable posting; it is not a net revenue/expense subtotal or tax base. It must equal the counterparty_posting amount for an ordinary invoice, include current-invoice taxes/fees, and exclude prior/next-period balances or settlement adjustments. Arithmetic derived from printed facts is allowed, but do not invent source amounts. "
    "Do not select or invent any customer/supplier/counterparty account code. Counterparty identity/account ownership belongs exclusively to semantic_plan. Do not emit a warning merely because semantic_plan intentionally reports no exact current account; the product will handle new-counterparty review separately. "
    "Put the balancing receivable/payable amount and direction only in counterparty_posting, which intentionally has no account_code. "
    "operating_journal_lines may contain only business, asset/inventory, expense/revenue, VAT and other tax/fee postings; never use them as a substitute counterparty receivable/payable. "
    "Independently select exact operating/tax accounts from chart_accounts. Use semantic_plan tax_components only as tax-type hints while source text remains amount authority. When a tax hint is non_vat_tax and a suitable distinct tax/levy account exists, do not bury that levy inside an operating expense. Use only real chart codes and treat each chart account name as authoritative semantic evidence. A code is not suitable merely because it exists or has a vaguely related numeric family; do not choose an account whose name implies a different event or counterparty type, such as a bank-interest/commission account for a non-bank supplier charge. If no suitable business or tax account exists, leave account_code empty instead of choosing a merely similar account. vat_input should use suitable 191 when available; vat_output suitable 391; non_vat_tax must not be treated as VAT. "
    "Raw rows may contain gross values, discounts and net values for the same economic event. row_decisions must cover every visible SATIR, but journal lines do not need one posting per raw row. "
    "For purchase invoices, discount_or_reduction rows normally reduce the related purchase or expense amount. Do not use sales contra-revenue accounts such as 610, 611 or 612 merely to represent a supplier invoice discount. Create a separate discount posting only when the source shows a distinct accounting event and the chosen chart account has purchase-side semantics. "
    "Return exactly one row_decision for every visible SATIR, even when multiple rows aggregate into one journal line or a row is discount/informational. row_decisions are audit coverage, not a requirement for separate postings. Copy only the source position marker such as 1 or SATIR 1; do not append the row description to source_position. Use canonical decimal strings. Current-invoice posting basis must exclude prior/next settlement balances when the source distinguishes them."
)


def _money(value: object) -> Decimal:
    text = str(value or "").strip().replace("TRY", "").replace("TL", "").replace("₺", "").replace(" ", "")
    if not text:
        return Decimal("0")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money_text(value: object) -> str:
    return f"{_money(value):.2f}"


def _workspace_accounts(workspace: Mapping[str, object]) -> list[dict[str, object]]:
    chart = workspace.get("chart_accounts")
    chart = chart if isinstance(chart, Mapping) else {}
    values = chart.get("accounts") or workspace.get("accounts") or ()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)]
def _chart_parts(workspace: Mapping[str, object]) -> tuple[str, str, dict[str, str]]:
    full_rows: list[str] = []
    current_rows: list[str] = []
    account_names: dict[str, str] = {}
    for item in _workspace_accounts(workspace):
        if item.get("is_detail_account") is False:
            continue
        raw_code = str(item.get("normalized_account_code") or item.get("account_code") or item.get("code") or "")
        code = normalize_account_code(raw_code)
        name = str(item.get("account_name") or item.get("name") or "").strip()
        if not code or not name:
            continue
        account_names[code] = name
        tax_id = str(item.get("tax_id") or "").strip()
        text = f"{code} | {name}" + (f" | tax_id={tax_id}" if tax_id else "")
        full_rows.append(text)
        if code.startswith(("120", "320", "329")):
            current_rows.append(text)
    return "\n".join(full_rows), "\n".join(current_rows), account_names


def render_source_text(package: Mapping[str, object]) -> str:
    output = ["# FATURA KAYNAK METNİ", "", "## BELGE"]
    for item in package.get("document_header") or []:
        if isinstance(item, Mapping):
            output.append(f"{item.get('label', '')}: {item.get('value', '')}")
    output += ["", "## ANA TARAFLAR"]
    for index, party in enumerate(package.get("principal_parties") or [], start=1):
        if not isinstance(party, Mapping):
            continue
        heading = str(party.get("heading") or "").strip()
        output += ["", f"### TARAF {index}" + (f" — {heading}" if heading else ""), f"Ad / Ünvan: {party.get('primary_name', '')}"]
        for item in party.get("detail_lines") or []:
            if isinstance(item, Mapping):
                output.append(f"{item.get('label', '')}: {item.get('value', '')}")
    output += ["", "## FATURA TABLOSU", str(package.get("invoice_table_header") or "")]
    for row in package.get("invoice_table_rows") or []:
        if isinstance(row, Mapping):
            output.append(f"SATIR {row.get('source_position', '')}: {row.get('source_text', '')}")
    output += ["", "## FATURADA BASILI DİĞER TUTARLAR"]
    for item in package.get("printed_summary_lines") or []:
        if isinstance(item, Mapping):
            output.append(f"{item.get('label', '')}: {item.get('value', '')}")
    output += ["", "## NOTLAR VE DİĞER BİLGİLER"]
    output += [str(item) for item in package.get("note_lines") or []]
    return "\n".join(output).strip() + "\n"


def _normalized_label(value: object) -> str:
    text = str(value or "").upper()
    replacements = str.maketrans("ÇĞİÖŞÜ", "CGIOSU")
    return re.sub(r"[^A-Z0-9]+", " ", text.translate(replacements)).strip()


def _find_labeled(items: object, *needles: str) -> str:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return ""
    normalized_needles = tuple(_normalized_label(item) for item in needles)
    for item in items:
        if not isinstance(item, Mapping):
            continue
        label = _normalized_label(item.get("label"))
        if any(needle and needle in label for needle in normalized_needles):
            return str(item.get("value") or "").strip()
    return ""


def _party_tax_id(party: Mapping[str, object]) -> str:
    for item in party.get("detail_lines") or []:
        if not isinstance(item, Mapping):
            continue
        label = _normalized_label(item.get("label"))
        if any(token in label for token in ("VKN", "TCKN", "VERGI KIMLIK", "TC KIMLIK")):
            return re.sub(r"\D", "", str(item.get("value") or ""))
    return ""


def _source_line_numbers(values: object) -> list[int]:
    result: list[int] = []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return result
    for value in values:
        match = re.search(r"\d+", str(value or ""))
        if match:
            number = int(match.group())
            if number not in result:
                result.append(number)
    return result
def _canonical_invoice(package: Mapping[str, object], source_sha256: str, direction: str) -> dict[str, object]:
    header = package.get("document_header") or []
    rows = package.get("invoice_table_rows") or []
    canonical_rows: list[dict[str, object]] = []
    for ordinal, raw in enumerate(rows, start=1):
        if not isinstance(raw, Mapping):
            continue
        position = str(raw.get("source_position") or ordinal)
        source_text = str(raw.get("source_text") or "")
        material = f"{source_sha256}|{ordinal}|{position}|{source_text}"
        canonical_rows.append({
            "canonical_line_id": "line_" + sha256(material.encode("utf-8")).hexdigest()[:24],
            "source_position": position,
            "description": source_text,
            "quantity": "",
            "unit_code": "",
            "unit_price": "",
            "taxable_amount": "",
            "vat_rate": "",
            "tax_amount": "",
            "gross_amount": "",
            "evidence": [source_text],
        })
    invoice_no = _find_labeled(header, "FATURA NO", "FATURA ID", "INVOICE NO")
    issue_date = _find_labeled(header, "FATURA TARIH", "TARIH", "ISSUE DATE")
    ettn = _find_labeled(header, "ETTN", "UUID")
    payable = _find_labeled(package.get("printed_summary_lines"), "ODENECEK TOPLAM", "ODENECEK TUTAR", "PAYABLE")
    return {
        "header": {"invoice_no": invoice_no, "ettn": ettn, "issue_date": issue_date, "currency": "TRY", "currency_code": "TRY", "document_direction": direction},
        "supplier_party": {},
        "customer_party": {},
        "line_items": canonical_rows,
        "totals": {"goods_services_total": "0.00", "vat_total": "0.00", "special_tax_total": "0.00", "tax_inclusive_total": "0.00", "payable_total": _money_text(payable), "currency": "TRY"},
    }


def _call_structured(provider: object, *, schema_name: str, instructions: str, payload: Mapping[str, object], schema: Mapping[str, object], document_bytes: bytes = b"") -> Any:
    public = getattr(provider, "generate_structured_json", None)
    if callable(public):
        kwargs: dict[str, object] = {"schema_name": schema_name, "instructions": instructions, "user_payload": payload, "schema": schema}
        if document_bytes:
            kwargs["document_bytes"] = document_bytes
            kwargs["document_mime_type"] = "application/pdf"
        return public(**kwargs)
    private = getattr(provider, "_post_structured_json")
    return private(schema_name=schema_name, instructions=instructions, user_payload=payload, schema=schema)
def _compose_journal(final_output: Mapping[str, object], plan: Mapping[str, object], account_names: Mapping[str, str]) -> tuple[list[dict[str, object]], list[str]]:
    warnings: list[str] = []
    for raw in final_output.get("row_decisions") or []:
        if not isinstance(raw, Mapping):
            continue
        code = normalize_account_code(str(raw.get("account_code") or ""))
        if code and code not in account_names:
            warnings.append(f"row_decision_account_not_in_chart:{code}")
    lines: list[dict[str, object]] = []
    for raw in final_output.get("operating_journal_lines") or []:
        if not isinstance(raw, Mapping):
            continue
        line = dict(raw)
        code = normalize_account_code(str(line.get("account_code") or ""))
        if code and code not in account_names:
            warnings.append(f"account_not_in_chart:{code}")
            code = ""
        if code.startswith(_CURRENT_ACCOUNT_PREFIXES):
            warnings.append(f"operating_line_used_counterparty_family:{code}")
            code = ""
        line["account_code"] = code
        line["account_name"] = account_names.get(code, str(line.get("account_name") or "")) if code else str(line.get("account_name") or "")
        line["debit"] = _money_text(line.get("debit"))
        line["credit"] = _money_text(line.get("credit"))
        lines.append(line)

    posting = final_output.get("counterparty_posting")
    posting = posting if isinstance(posting, Mapping) else {}
    match = str(plan.get("counterparty_match") or "")
    code = normalize_account_code(str(plan.get("counterparty_account_code") or "")) if match == "exact" else ""
    if code and code not in account_names:
        warnings.append(f"planner_counterparty_not_in_chart:{code}")
        code = ""
    if not code:
        warnings.append("new_counterparty_required")
    lines.append({
        "account_code": code,
        "account_name": account_names.get(code, str(plan.get("counterparty_name") or "")),
        "description": str(posting.get("description") or plan.get("counterparty_name") or "Cari hesap"),
        "debit": _money_text(posting.get("debit")),
        "credit": _money_text(posting.get("credit")),
        "source_positions": list(posting.get("source_positions") or []),
    })
    return lines, warnings


def _draft_lines(lines: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        debit = _money(line.get("debit"))
        credit = _money(line.get("credit"))
        result.append({
            "fact_ref": f"three-stage:{index}",
            "proposal_role": "three_stage_ai",
            "account_code": str(line.get("account_code") or ""),
            "account_name": str(line.get("account_name") or ""),
            "description": str(line.get("description") or ""),
            "debit": f"{debit:.2f}",
            "credit": f"{credit:.2f}",
            "amount": f"{max(debit, credit):.2f}",
            "side": "debit" if debit > 0 else "credit" if credit > 0 else "",
            "source_basis": [str(item) for item in line.get("source_positions") or []],
            "source_line_numbers": _source_line_numbers(line.get("source_positions")),
            "warnings": [],
        })
    return result


def _source_review_rows(package: Mapping[str, object]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw in package.get("invoice_table_rows") or []:
        if not isinstance(raw, Mapping):
            continue
        result.append({
            "source_position": str(raw.get("source_position") or ""),
            "source_text": str(raw.get("source_text") or ""),
            "description": str(raw.get("description") or ""),
            "amount": str(raw.get("ui_amount") or ""),
            "amount_label": str(raw.get("ui_amount_label") or ""),
            "amount_basis": str(raw.get("ui_amount_basis") or "none"),
            "role": str(raw.get("ui_role") or "informational"),
        })
    return result


def _totals(lines: Sequence[Mapping[str, object]]) -> tuple[Decimal, Decimal]:
    debit = sum((_money(line.get("debit")) for line in lines), Decimal("0")).quantize(Decimal("0.01"))
    credit = sum((_money(line.get("credit")) for line in lines), Decimal("0")).quantize(Decimal("0.01"))
    return debit, credit


def _normalized_source_position(value: object) -> str:
    text = str(value or "").strip().upper()
    match = re.match(r"^(?:SATIR\s+)?(\d+)", text)
    return match.group(1) if match else re.sub(r"^SATIR\s+", "", text).strip()


def _row_coverage_warning(package: Mapping[str, object], final_output: Mapping[str, object]) -> list[str]:
    expected = [_normalized_source_position(item.get("source_position")) for item in package.get("invoice_table_rows") or [] if isinstance(item, Mapping)]
    actual = [_normalized_source_position(item.get("source_position")) for item in final_output.get("row_decisions") or [] if isinstance(item, Mapping)]
    return [] if expected == actual else ["row_coverage_incomplete"]


def _canonical_line_decisions(
    canonical: Mapping[str, object],
    final_output: Mapping[str, object],
    account_names: Mapping[str, str],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    canonical_rows = [item for item in canonical.get("line_items") or [] if isinstance(item, Mapping)]
    rows_by_position: dict[str, list[Mapping[str, object]]] = {}
    expected_ids: list[str] = []
    for row in canonical_rows:
        canonical_line_id = str(row.get("canonical_line_id") or "")
        if canonical_line_id:
            expected_ids.append(canonical_line_id)
        position = _normalized_source_position(row.get("source_position"))
        if position:
            rows_by_position.setdefault(position, []).append(row)

    decisions: list[dict[str, object]] = []
    received_ids: list[str] = []
    unmatched_positions: list[str] = []
    ambiguous_positions: list[str] = []
    for raw in final_output.get("row_decisions") or []:
        if not isinstance(raw, Mapping):
            continue
        decision = dict(raw)
        account_code = normalize_account_code(str(raw.get("account_code") or ""))
        decision["account_code"] = account_code if account_code in account_names else ""
        position = _normalized_source_position(raw.get("source_position"))
        matches = rows_by_position.get(position, [])
        canonical_line_id = ""
        if len(matches) == 1:
            canonical_line_id = str(matches[0].get("canonical_line_id") or "")
        elif len(matches) > 1:
            ambiguous_positions.append(position)
        else:
            unmatched_positions.append(position)
        decision["canonical_line_id"] = canonical_line_id
        decisions.append(decision)
        if canonical_line_id:
            received_ids.append(canonical_line_id)

    duplicate_ids = sorted({line_id for line_id in received_ids if received_ids.count(line_id) > 1})
    missing_ids = sorted(set(expected_ids) - set(received_ids))
    valid = bool(expected_ids) and len(decisions) == len(expected_ids) and not (
        missing_ids or duplicate_ids or unmatched_positions or ambiguous_positions
    )
    return decisions, {
        "status": "valid" if valid else "invalid",
        "expected_ids": expected_ids,
        "received_ids": received_ids,
        "missing_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
        "unknown_ids": [],
        "unmatched_source_positions": unmatched_positions,
        "ambiguous_source_positions": ambiguous_positions,
    }


def _party_projection(
    package: Mapping[str, object],
    plan: Mapping[str, object],
    client: Mapping[str, object] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    parties = [item for item in package.get("principal_parties") or [] if isinstance(item, Mapping)]
    our_index = str(plan.get("our_party_index") or "unknown")
    try:
        our_party = parties[int(our_index) - 1] if our_index in {"1", "2"} else {}
    except IndexError:
        our_party = {}
    client = client or {}
    counterparty_name = str(plan.get("counterparty_name") or "")
    counterparty = next((item for item in parties if str(item.get("primary_name") or "") == counterparty_name), {})
    own = {
        "title": str(our_party.get("primary_name") or client.get("title") or ""),
        "tax_id": _party_tax_id(our_party) or str(client.get("tax_id") or ""),
    }
    other = {"title": counterparty_name or str(counterparty.get("primary_name") or ""), "tax_id": str(plan.get("counterparty_identifier") or "") or _party_tax_id(counterparty)}
    return own, other


def _compatibility_result(*, package: Mapping[str, object], plan: Mapping[str, object], final_output: Mapping[str, object], journal_lines: list[dict[str, object]], account_names: Mapping[str, str], source_sha256: str, warnings: Sequence[str], stage_elapsed_ms: Mapping[str, int], reader_attempt: Any, planner_attempt: Any, final_provider: object, source_text: str, client: Mapping[str, object] | None = None) -> dict[str, Any]:
    direction = str(plan.get("accounting_direction") or "unknown")
    own, counterparty = _party_projection(package, plan, client)
    canonical = _canonical_invoice(package, source_sha256, direction)
    if direction == "sales":
        canonical["supplier_party"], canonical["customer_party"] = own, counterparty
    else:
        canonical["supplier_party"], canonical["customer_party"] = counterparty, own
    line_decisions, line_decision_coverage = _canonical_line_decisions(canonical, final_output, account_names)
    draft_lines = _draft_lines(journal_lines)
    debit, credit = _totals(journal_lines)
    reason_codes = list(dict.fromkeys(str(item) for item in warnings if str(item).strip()))
    final_failed = str(final_output.get("_stage_status") or "") == "failed" or "final_accountant_unavailable" in reason_codes
    if debit != credit:
        reason_codes.append("draft_unbalanced")
    if any(not str(line.get("account_code") or "") for line in draft_lines):
        reason_codes.append("draft_account_missing")
    reason_codes = list(dict.fromkeys(reason_codes))
    first_business = next((line for line in draft_lines if str(line.get("account_code") or "").startswith(("6", "7", "15"))), {})
    first_vat = next((line for line in draft_lines if str(line.get("account_code") or "").startswith(("191", "391"))), {})
    party_code = str(plan.get("counterparty_account_code") or "") if plan.get("counterparty_match") == "exact" else ""
    header = package.get("document_header") or []
    summaries = package.get("printed_summary_lines") or []
    invoice_no = _find_labeled(header, "FATURA NO", "FATURA ID", "INVOICE NO")
    issue_date = _find_labeled(header, "FATURA TARIH", "TARIH", "ISSUE DATE")
    payable = _find_labeled(summaries, "ODENECEK TOPLAM", "ODENECEK TUTAR", "PAYABLE")
    pipeline_warnings = list(
        dict.fromkeys([
            *reason_codes,
            *[str(item) for item in final_output.get("_account_repair_trigger_warnings") or []],
        ])
    )
    posting_basis_raw = str(final_output.get("posting_basis_amount") or "").strip()
    payable_raw = str(payable or "").strip()
    no_posting_required = bool(
        not final_failed
        and posting_basis_raw
        and payable_raw
        and debit == Decimal("0.00")
        and credit == Decimal("0.00")
        and _money(posting_basis_raw) == Decimal("0.00")
        and _money(payable_raw) == Decimal("0.00")
        and str(line_decision_coverage.get("status") or "") == "valid"
        and not _invalid_account_warnings(reason_codes)
    )
    if no_posting_required:
        reason_codes = []
        draft_lines = []
        first_business = {}
        first_vat = {}
    journal_vat_total = sum(
        max(_money(line.get("debit")), _money(line.get("credit")))
        for line in draft_lines
        if str(line.get("account_code") or "").startswith(("191", "391"))
    )
    printed_vat_total = _find_labeled(summaries, "HESAPLANAN KDV", "KDV TUTAR", "VAT TOTAL", "VAT AMOUNT")
    vat_total = f"{journal_vat_total:.2f}" if journal_vat_total else _money_text(printed_vat_total)
    summary = str(final_output.get("summary") or "Üç aşamalı AI muhasebe taslağı hazırlandı.")
    if no_posting_required:
        summary = "Sıfır tutarlı fatura; muhasebe fişi gerekmiyor. Belge ve kaynak satırları saklandı."
    final_model = str(getattr(final_provider, "model", "") or "")
    return {
        "invoice_no": invoice_no,
        "issue_date": issue_date,
        "invoice_date": issue_date,
        "currency_code": "TRY",
        "accounting_direction": direction,
        "supplier_title": str(canonical["supplier_party"].get("title") or ""),
        "supplier_tax_id": str(canonical["supplier_party"].get("tax_id") or ""),
        "customer_title": str(canonical["customer_party"].get("title") or ""),
        "customer_tax_id": str(canonical["customer_party"].get("tax_id") or ""),
        "counterparty_title": counterparty["title"],
        "counterparty_tax_id": counterparty["tax_id"],
        "goods_services_total": "0.00",
        "vat_total": vat_total,
        "special_tax_total": "0.00",
        "tax_inclusive_total": _money_text(final_output.get("posting_basis_amount")),
        "payable_total": _money_text(payable or final_output.get("posting_basis_amount")),
        "canonical_invoice": canonical,
        "canonical_line_count": len(canonical.get("line_items") or []),
        "source_review_rows": _source_review_rows(package),
        "source_review_row_count": len(package.get("invoice_table_rows") or []),
        "source_review_posting_candidate_count": sum(
            1 for row in package.get("invoice_table_rows") or []
            if isinstance(row, Mapping) and str(row.get("ui_role") or "") == "posting_candidate"
        ),
        "canonical_validation_status": "source_reconstruction",
        "canonical_validation_reasons": reason_codes,
        "canonical_extraction_ai_used": True,
        "draft_lines": draft_lines,
        "line_decisions": line_decisions,
        "line_decision_coverage": line_decision_coverage,
        "total_debit": f"{debit:.2f}",
        "total_credit": f"{credit:.2f}",
        "is_balanced": debit == credit,
        "selected_expense_account": str(first_business.get("account_code") or "") if direction != "sales" else "",
        "selected_revenue_account": str(first_business.get("account_code") or "") if direction == "sales" else "",
        "selected_vat_account": str(first_vat.get("account_code") or ""),
        "selected_purchase_vat_account": str(first_vat.get("account_code") or "") if direction != "sales" else "",
        "selected_sales_vat_account": str(first_vat.get("account_code") or "") if direction == "sales" else "",
        "selected_supplier_account": party_code if direction != "sales" else "",
        "selected_customer_account": party_code if direction == "sales" else "",
        "counterparty_match_code": party_code,
        "status": "no_posting_required" if no_posting_required else ("complete" if debit == credit and not reason_codes else "partial"),
        "simulated_status": "no_posting_required" if no_posting_required else "review_required",
        "draft_status": "no_posting_required" if no_posting_required else "review_required",
        "processing_status": "completed",
        "extraction_validation_status": "source_reconstruction",
        "reconciliation_status": "not_applicable" if no_posting_required else ("warning" if reason_codes else "not_required"),
        "accounting_decision_status": "no_posting_required" if no_posting_required else "best_effort",
        "draft_balance_status": "not_applicable" if no_posting_required else ("balanced" if debit == credit else "unbalanced"),
        "review_status": "no_posting_required" if no_posting_required else "review_required",
        "export_status": "no_posting_required" if no_posting_required else "review_required",
        "automation_eligibility": "not_applicable" if no_posting_required else "not_eligible",
        "posting_status": "no_posting_required" if no_posting_required else "draft_created",
        "ai_resolution_status": "ai_retry_required" if final_failed else "",
        "ai_retry_reason": "final_accountant_unavailable" if final_failed else "",
        "three_stage_account_repair_attempted": bool(final_output.get("_account_repair_attempted")),
        "three_stage_account_repair_status": str(final_output.get("_account_repair_status") or ""),
        "three_stage_account_repair_elapsed_ms": int(final_output.get("_account_repair_elapsed_ms") or 0),
        "three_stage_account_repair_reason_codes": [str(item) for item in final_output.get("_account_repair_trigger_warnings") or []],
        "three_stage_account_repair_error_type": str(final_output.get("_account_repair_error_type") or ""),
        "three_stage_self_repair_attempted": bool(final_output.get("_repair_attempted")),
        "three_stage_self_repair_status": str(final_output.get("_repair_status") or ""),
        "three_stage_self_repair_elapsed_ms": int(final_output.get("_repair_elapsed_ms") or 0),
        "pipeline_warnings": pipeline_warnings,
        "review_reason_codes": reason_codes,
        "risk_flags": reason_codes,
        "confidence_label": "Fiş gerektirmeyen sıfır tutarlı belge" if no_posting_required else "Müşavir onayı gereken üç aşamalı AI taslağı",
        "accountant_action_hint": "Fiş oluşturulmadı; belge kaynak kaydı olarak saklandı." if no_posting_required else "Taslak hazır; müşavir tek tıkla onaylayabilir.",
        "accountant_summary": summary,
        "accountant_explanation_tr": summary,
        "decision_narrative": {
            "read_facts": {"invoice_no": invoice_no, "direction": direction, "counterparty_title": counterparty["title"], "payable_total": _money_text(payable), "posting_basis": _money_text(final_output.get("posting_basis_amount"))},
            "fisora_interpretation": summary,
            "account_code": str(first_business.get("account_code") or ""),
            "account_name": account_names.get(str(first_business.get("account_code") or ""), str(first_business.get("account_name") or "")),
        },
        "ai_classification_used": True,
        "ai_classification_provider": "xkiro",
        "ai_model": final_model,
        "ai_first_rescue_used": False,
        "three_stage_accounting_used": True,
        "pipeline_version": PIPELINE_VERSION,
        "three_stage_posting_basis_label": str(final_output.get("posting_basis_label") or ""),
        "three_stage_posting_basis_amount": _money_text(final_output.get("posting_basis_amount")),
        "three_stage_source_text": source_text,
        "three_stage_semantic_plan": dict(plan),
        "three_stage_identity_plan": dict(plan),
        "three_stage_stage_elapsed_ms": dict(stage_elapsed_ms),
        "ai_trace": [
            {"stage": "source_reader", "provider": str(getattr(reader_attempt, "provider", "gemini") or "gemini"), "model": str(getattr(reader_attempt, "resolved_model", "") or getattr(reader_attempt, "model_alias", "") or ""), "status": str(getattr(reader_attempt, "status", "successful") or "successful"), "elapsed_ms": int(stage_elapsed_ms.get("reader", 0))},
            {"stage": "identity_planner", "provider": str(getattr(planner_attempt, "provider", "gemini") or "gemini"), "model": str(getattr(planner_attempt, "resolved_model", "") or getattr(planner_attempt, "model_alias", "") or ""), "status": str(getattr(planner_attempt, "status", "successful") or "successful"), "elapsed_ms": int(stage_elapsed_ms.get("planner", 0))},
            {"stage": "final_accountant", "provider": str(getattr(final_provider, "provider_name", "xkiro") or "xkiro"), "model": final_model, "status": str(final_output.get("_stage_status") or "successful"), "elapsed_ms": int(stage_elapsed_ms.get("accountant", 0))},
        ] + ([{"stage": "final_accountant_account_repair", "provider": str(getattr(final_provider, "provider_name", "xkiro") or "xkiro"), "model": final_model, "status": str(final_output.get("_account_repair_status") or "failed"), "elapsed_ms": int(final_output.get("_account_repair_elapsed_ms") or 0)}] if final_output.get("_account_repair_attempted") else []) + ([{"stage": "final_accountant_repair", "provider": str(getattr(final_provider, "provider_name", "xkiro") or "xkiro"), "model": final_model, "status": str(final_output.get("_repair_status") or "failed"), "elapsed_ms": int(final_output.get("_repair_elapsed_ms") or 0)}] if final_output.get("_repair_attempted") else []),
    }


def run_source_reader_stage(*, provider: object, source_bytes: bytes) -> tuple[dict[str, Any], str, Any, int]:
    if not source_bytes.startswith(b"%PDF"):
        raise ValueError("three-stage accounting requires PDF bytes")
    started = perf_counter()
    raw = _call_structured(
        provider,
        schema_name="fisora_invoice_source_reconstruction_v4",
        instructions=READER_INSTRUCTIONS,
        payload={"task": "source_reconstruction_only"},
        schema=READER_SCHEMA,
        document_bytes=source_bytes,
    )
    elapsed_ms = round((perf_counter() - started) * 1000)
    package = dict(raw)
    return package, render_source_text(package), getattr(raw, "attempt", None), elapsed_ms


def run_semantic_planner_stage(*, provider: object, source_text: str, client: Mapping[str, object], current_candidates: str, expected_direction: str) -> tuple[dict[str, Any], Any, int]:
    started = perf_counter()
    raw = _call_structured(
        provider,
        schema_name="fisora_semantic_planner",
        instructions=PLANNER_INSTRUCTIONS,
        payload={
            "client": dict(client),
            "expected_direction": expected_direction,
            "invoice_source_text": source_text,
            "current_counterparty_candidates": current_candidates,
        },
        schema=PLANNER_SCHEMA,
    )
    elapsed_ms = round((perf_counter() - started) * 1000)
    return dict(raw), getattr(raw, "attempt", None), elapsed_ms


def run_final_accountant_stage(*, provider: object, source_text: str, semantic_plan: Mapping[str, object], chart_text: str, client: Mapping[str, object] | None = None, expected_direction: str = "", repair_context: Mapping[str, object] | None = None) -> tuple[dict[str, Any], int]:
    started = perf_counter()
    final_error: Exception | None = None
    instructions = ACCOUNTANT_INSTRUCTIONS
    payload: dict[str, object] = {"client": dict(client or {}), "expected_direction": expected_direction, "invoice_source_text": source_text, "semantic_plan": dict(semantic_plan), "chart_accounts": chart_text}
    if repair_context:
        payload["repair_context"] = dict(repair_context)
        repair_reason = str(repair_context.get("reason") or "unbalanced")
        if repair_reason == "invalid_account_code":
            instructions += " A previous draft used one or more account codes that are not exact members of chart_accounts. Re-evaluate the same source facts and return a complete corrected draft. Copy account_code values exactly from chart_accounts; do not zero-pad, abbreviate, normalize, synthesize or otherwise rewrite a chart code. If no suitable exact chart account exists, leave account_code empty."
        else:
            instructions += " A previous draft was rejected because debit and credit were not equal. Re-evaluate the same source facts and return a complete corrected draft. Do not invent amounts, do not add an unsupported balancing line, and do not alter printed source totals merely to force balance."
    for final_attempt_no in range(2):
        try:
            raw = _call_structured(
                provider,
                schema_name="fisora_planner_owned_counterparty_accountant",
                instructions=instructions,
                payload=payload,
                schema=ACCOUNTANT_SCHEMA,
            )
            return dict(raw), round((perf_counter() - started) * 1000)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            final_error = exc
            retryable_status = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {429, 500, 502, 503, 504}
            if final_attempt_no == 1 or (isinstance(exc, httpx.HTTPStatusError) and not retryable_status):
                raise
    assert final_error is not None
    raise final_error


def _invalid_account_warnings(warnings: Sequence[str]) -> list[str]:
    return [
        str(warning)
        for warning in warnings
        if str(warning).startswith(("account_not_in_chart:", "row_decision_account_not_in_chart:"))
    ]


def _repaired_output_uses_exact_chart_codes(
    final_output: Mapping[str, object],
    account_names: Mapping[str, str],
) -> bool:
    for section in ("operating_journal_lines", "row_decisions"):
        for raw in final_output.get(section) or []:
            if not isinstance(raw, Mapping):
                continue
            code = str(raw.get("account_code") or "").strip()
            if code and code not in account_names:
                return False
    for raw in final_output.get("operating_journal_lines") or []:
        if not isinstance(raw, Mapping):
            continue
        has_amount = _money(raw.get("debit")) > 0 or _money(raw.get("credit")) > 0
        if has_amount and not str(raw.get("account_code") or "").strip():
            return False
    return True


def _repair_invalid_account_codes(
    *,
    provider: object,
    source_text: str,
    semantic_plan: Mapping[str, object],
    chart_text: str,
    account_names: Mapping[str, str],
    client: Mapping[str, object],
    expected_direction: str,
    final_output: dict[str, Any],
    journal_lines: list[dict[str, object]],
    composition_warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, object]], list[str], int]:
    invalid_warnings = _invalid_account_warnings(composition_warnings)
    if not invalid_warnings:
        return final_output, journal_lines, composition_warnings, 0

    started = perf_counter()
    status = "failed"
    error_type = ""
    elapsed_ms = 0
    try:
        repaired_output, elapsed_ms = run_final_accountant_stage(
            provider=provider,
            source_text=source_text,
            semantic_plan=semantic_plan,
            chart_text=chart_text,
            client=client,
            expected_direction=expected_direction,
            repair_context={
                "reason": "invalid_account_code",
                "invalid_account_warnings": invalid_warnings,
                "previous_draft": dict(final_output),
            },
        )
        repaired_lines, repaired_warnings = _compose_journal(repaired_output, semantic_plan, account_names)
        if _invalid_account_warnings(repaired_warnings):
            status = "invalid_account_code"
        elif not _repaired_output_uses_exact_chart_codes(repaired_output, account_names):
            status = "account_code_not_exact"
        else:
            final_output = repaired_output
            journal_lines = repaired_lines
            composition_warnings = repaired_warnings
            status = "successful"
    except Exception as exc:
        error_type = type(exc).__name__
        elapsed_ms = round((perf_counter() - started) * 1000)

    final_output["_account_repair_attempted"] = True
    final_output["_account_repair_status"] = status
    final_output["_account_repair_elapsed_ms"] = elapsed_ms
    final_output["_account_repair_trigger_warnings"] = invalid_warnings
    final_output["_account_repair_error_type"] = error_type
    if status != "successful":
        composition_warnings = [*composition_warnings, f"invalid_account_self_repair_{status}"]
    return final_output, journal_lines, composition_warnings, elapsed_ms


def run_prepared_source_accounting_pipeline(
    *,
    planner_provider: object,
    final_provider: object,
    source_package: Mapping[str, object],
    planner_source_text: str,
    accountant_source_text: str,
    source_sha256: str,
    workspace: Mapping[str, object],
    tenant_tax_id: str = "",
    expected_direction: str = "",
    client_context: Mapping[str, object] | None = None,
    reader_elapsed_ms: int = 0,
    reader_attempt: Any = None,
    stage_observer: Callable[[str, Mapping[str, object]], None] | None = None,
) -> ThreeStageAccountingRun:
    """Run Planner and Final Accountant from a validated deterministic source package."""

    package = dict(source_package)
    chart_text, current_candidates, account_names = _chart_parts(workspace)
    profile = workspace.get("client") if isinstance(workspace.get("client"), Mapping) else {}
    profile = profile.get("profile") if isinstance(profile.get("profile"), Mapping) else profile
    client = {
        "title": str(profile.get("title") or profile.get("name") or ""),
        "tax_id": tenant_tax_id,
        "activity": dict(client_context or {}),
    }

    planner_started = perf_counter()
    try:
        semantic_plan, planner_attempt, planner_ms = run_semantic_planner_stage(
            provider=planner_provider,
            source_text=planner_source_text,
            client=client,
            current_candidates=current_candidates,
            expected_direction=expected_direction,
        )
    except Exception as exc:
        if stage_observer is not None:
            stage_observer(
                "planner_failed",
                {
                    "status": "failed",
                    "elapsed_ms": round((perf_counter() - planner_started) * 1000),
                    "error_type": type(exc).__name__,
                },
            )
        raise
    if stage_observer is not None:
        stage_observer("planner_completed", {"semantic_plan": semantic_plan, "elapsed_ms": planner_ms})

    final_started = perf_counter()
    try:
        final_output, accountant_ms = run_final_accountant_stage(
            provider=final_provider,
            source_text=accountant_source_text,
            semantic_plan=semantic_plan,
            chart_text=chart_text,
            client=client,
            expected_direction=expected_direction,
        )
    except Exception as exc:
        accountant_ms = round((perf_counter() - final_started) * 1000)
        final_output = {
            "warnings": ["final_accountant_unavailable"],
            "summary": "Kaynak satırlar hazır; muhasebe önerisi alınamadı.",
            "_stage_status": "failed",
            "_stage_error_type": type(exc).__name__,
        }

    account_repair_ms = 0
    repair_ms = 0
    if str(final_output.get("_stage_status") or "") == "failed":
        journal_lines, composition_warnings = [], []
    else:
        journal_lines, composition_warnings = _compose_journal(final_output, semantic_plan, account_names)
        final_output, journal_lines, composition_warnings, account_repair_ms = _repair_invalid_account_codes(
            provider=final_provider,
            source_text=accountant_source_text,
            semantic_plan=semantic_plan,
            chart_text=chart_text,
            account_names=account_names,
            client=client,
            expected_direction=expected_direction,
            final_output=final_output,
            journal_lines=journal_lines,
            composition_warnings=composition_warnings,
        )
        debit_before_repair, credit_before_repair = _totals(journal_lines)
        if journal_lines and debit_before_repair != credit_before_repair:
            repair_started = perf_counter()
            repair_status = "failed"
            repair_context = {
                "computed_total_debit": f"{debit_before_repair:.2f}",
                "computed_total_credit": f"{credit_before_repair:.2f}",
                "difference": f"{abs(debit_before_repair-credit_before_repair):.2f}",
                "previous_draft": dict(final_output),
            }
            try:
                repaired_output, repair_ms = run_final_accountant_stage(
                    provider=final_provider,
                    source_text=accountant_source_text,
                    semantic_plan=semantic_plan,
                    chart_text=chart_text,
                    client=client,
                    expected_direction=expected_direction,
                    repair_context=repair_context,
                )
                repaired_lines, repaired_warnings = _compose_journal(repaired_output, semantic_plan, account_names)
                repaired_debit, repaired_credit = _totals(repaired_lines)
                repaired_invalid_accounts = _invalid_account_warnings(repaired_warnings)
                if repaired_invalid_accounts or not _repaired_output_uses_exact_chart_codes(repaired_output, account_names):
                    composition_warnings = [*composition_warnings, *repaired_invalid_accounts]
                    repair_status = "invalid_account_code"
                elif repaired_lines and repaired_debit == repaired_credit:
                    for key in (
                        "_account_repair_attempted",
                        "_account_repair_status",
                        "_account_repair_elapsed_ms",
                        "_account_repair_trigger_warnings",
                        "_account_repair_error_type",
                    ):
                        if key in final_output:
                            repaired_output[key] = final_output[key]
                    final_output, journal_lines, composition_warnings = repaired_output, repaired_lines, repaired_warnings
                    repair_status = "successful"
                else:
                    repair_status = "unbalanced"
            except Exception:
                repair_ms = round((perf_counter() - repair_started) * 1000)
            final_output["_repair_attempted"] = True
            final_output["_repair_status"] = repair_status
            final_output["_repair_elapsed_ms"] = repair_ms
            if repair_status != "successful":
                composition_warnings = [*composition_warnings, f"unbalanced_self_repair_{repair_status}"]

    if stage_observer is not None:
        stage_observer(
            "final_completed",
            {
                "status": "failed" if str(final_output.get("_stage_status") or "") == "failed" else "completed",
                "elapsed_ms": accountant_ms + account_repair_ms + repair_ms,
            },
        )
    warnings = [
        *[str(item) for item in final_output.get("warnings") or [] if str(item).strip()],
        *composition_warnings,
        *_row_coverage_warning(package, final_output),
    ]
    stage_elapsed_ms = {
        "reader": max(int(reader_elapsed_ms), 0),
        "planner": planner_ms,
        "accountant": accountant_ms,
        "accountant_account_repair": account_repair_ms,
        "accountant_repair": repair_ms,
        "total": max(int(reader_elapsed_ms), 0) + planner_ms + accountant_ms + account_repair_ms + repair_ms,
    }
    prepared_reader_attempt = reader_attempt or SimpleNamespace(provider="prepared_source", resolved_model="", model_alias="", status="successful")
    result = _compatibility_result(
        package=package,
        plan=semantic_plan,
        final_output=final_output,
        journal_lines=journal_lines,
        account_names=account_names,
        source_sha256=source_sha256,
        warnings=warnings,
        stage_elapsed_ms=stage_elapsed_ms,
        reader_attempt=prepared_reader_attempt,
        planner_attempt=planner_attempt,
        final_provider=final_provider,
        source_text=accountant_source_text,
        client=client,
    )
    return ThreeStageAccountingRun(
        result=result,
        source_package=package,
        source_text=accountant_source_text,
        semantic_plan=semantic_plan,
        final_output=final_output,
        reader_attempt=prepared_reader_attempt,
        planner_attempt=planner_attempt,
        stage_elapsed_ms=stage_elapsed_ms,
    )


def run_three_stage_accounting_pipeline(
    *, reader_provider: object, final_provider: object, source_bytes: bytes,
    source_sha256: str, workspace: Mapping[str, object], tenant_tax_id: str = "",
    expected_direction: str = "", client_context: Mapping[str, object] | None = None,
    stage_observer: Callable[[str, Mapping[str, object]], None] | None = None,
) -> ThreeStageAccountingRun:
    if not source_bytes.startswith(b"%PDF"):
        raise ValueError("three-stage accounting requires PDF bytes")
    chart_text, current_candidates, account_names = _chart_parts(workspace)
    profile = workspace.get("client") if isinstance(workspace.get("client"), Mapping) else {}
    profile = profile.get("profile") if isinstance(profile.get("profile"), Mapping) else profile
    client = {
        "title": str(profile.get("title") or profile.get("name") or ""),
        "tax_id": tenant_tax_id,
        "activity": dict(client_context or {}),
    }

    reader_started = perf_counter()
    try:
        source_package, source_text, reader_attempt, reader_ms = run_source_reader_stage(
            provider=reader_provider, source_bytes=source_bytes,
        )
    except Exception as exc:
        if stage_observer is not None:
            stage_observer("reader_failed", {"status": "failed", "elapsed_ms": round((perf_counter() - reader_started) * 1000), "error_type": type(exc).__name__})
        raise
    if stage_observer is not None:
        stage_observer("reader_completed", {"source_package": source_package, "elapsed_ms": reader_ms})

    planner_started = perf_counter()
    try:
        semantic_plan, planner_attempt, planner_ms = run_semantic_planner_stage(
            provider=reader_provider, source_text=source_text, client=client,
            current_candidates=current_candidates, expected_direction=expected_direction,
        )
    except Exception as exc:
        if stage_observer is not None:
            stage_observer("planner_failed", {"status": "failed", "elapsed_ms": round((perf_counter() - planner_started) * 1000), "error_type": type(exc).__name__})
        raise
    if stage_observer is not None:
        stage_observer("planner_completed", {"semantic_plan": semantic_plan, "elapsed_ms": planner_ms})
    final_started = perf_counter()
    try:
        final_output, accountant_ms = run_final_accountant_stage(
            provider=final_provider, source_text=source_text, semantic_plan=semantic_plan, chart_text=chart_text,
            client=client, expected_direction=expected_direction,
        )
    except Exception as exc:
        accountant_ms = round((perf_counter() - final_started) * 1000)
        final_output = {
            "warnings": ["final_accountant_unavailable"],
            "summary": "Kaynak satırlar hazır; muhasebe önerisi alınamadı.",
            "_stage_status": "failed",
            "_stage_error_type": type(exc).__name__,
        }

    account_repair_ms = 0
    repair_ms = 0
    if str(final_output.get("_stage_status") or "") == "failed":
        journal_lines, composition_warnings = [], []
    else:
        journal_lines, composition_warnings = _compose_journal(final_output, semantic_plan, account_names)
        final_output, journal_lines, composition_warnings, account_repair_ms = _repair_invalid_account_codes(
            provider=final_provider,
            source_text=source_text,
            semantic_plan=semantic_plan,
            chart_text=chart_text,
            account_names=account_names,
            client=client,
            expected_direction=expected_direction,
            final_output=final_output,
            journal_lines=journal_lines,
            composition_warnings=composition_warnings,
        )
        debit_before_repair, credit_before_repair = _totals(journal_lines)
        if journal_lines and debit_before_repair != credit_before_repair:
            repair_started = perf_counter()
            repair_status = "failed"
            repair_context = {"computed_total_debit": f"{debit_before_repair:.2f}", "computed_total_credit": f"{credit_before_repair:.2f}", "difference": f"{abs(debit_before_repair-credit_before_repair):.2f}", "previous_draft": dict(final_output)}
            try:
                repaired_output, repair_ms = run_final_accountant_stage(provider=final_provider, source_text=source_text, semantic_plan=semantic_plan, chart_text=chart_text, client=client, expected_direction=expected_direction, repair_context=repair_context)
                repaired_lines, repaired_warnings = _compose_journal(repaired_output, semantic_plan, account_names)
                repaired_debit, repaired_credit = _totals(repaired_lines)
                repaired_invalid_accounts = _invalid_account_warnings(repaired_warnings)
                if repaired_invalid_accounts or not _repaired_output_uses_exact_chart_codes(repaired_output, account_names):
                    composition_warnings = [*composition_warnings, *repaired_invalid_accounts]
                    repair_status = "invalid_account_code"
                elif repaired_lines and repaired_debit == repaired_credit:
                    for key in (
                        "_account_repair_attempted",
                        "_account_repair_status",
                        "_account_repair_elapsed_ms",
                        "_account_repair_trigger_warnings",
                        "_account_repair_error_type",
                    ):
                        if key in final_output:
                            repaired_output[key] = final_output[key]
                    final_output, journal_lines, composition_warnings = repaired_output, repaired_lines, repaired_warnings
                    repair_status = "successful"
                else:
                    repair_status = "unbalanced"
            except Exception:
                repair_ms = round((perf_counter() - repair_started) * 1000)
            final_output["_repair_attempted"] = True
            final_output["_repair_status"] = repair_status
            final_output["_repair_elapsed_ms"] = repair_ms
            if repair_status != "successful":
                composition_warnings = [*composition_warnings, f"unbalanced_self_repair_{repair_status}"]
    if stage_observer is not None:
        stage_observer(
            "final_completed",
            {"status": "failed" if str(final_output.get("_stage_status") or "") == "failed" else "completed",
             "elapsed_ms": accountant_ms + account_repair_ms + repair_ms},
        )
    warnings = [
        *[str(item) for item in final_output.get("warnings") or [] if str(item).strip()],
        *composition_warnings,
        *_row_coverage_warning(source_package, final_output),
    ]
    stage_elapsed_ms = {"reader": reader_ms, "planner": planner_ms, "accountant": accountant_ms, "accountant_account_repair": account_repair_ms, "accountant_repair": repair_ms, "total": reader_ms + planner_ms + accountant_ms + account_repair_ms + repair_ms}
    result = _compatibility_result(
        package=source_package,
        plan=semantic_plan,
        final_output=final_output,
        journal_lines=journal_lines,
        account_names=account_names,
        source_sha256=source_sha256,
        warnings=warnings,
        stage_elapsed_ms=stage_elapsed_ms,
        reader_attempt=reader_attempt,
        planner_attempt=planner_attempt,
        final_provider=final_provider,
        source_text=source_text,
    )
    return ThreeStageAccountingRun(
        result=result,
        source_package=source_package,
        source_text=source_text,
        semantic_plan=semantic_plan,
        final_output=final_output,
        reader_attempt=reader_attempt,
        planner_attempt=planner_attempt,
        stage_elapsed_ms=stage_elapsed_ms,
    )
