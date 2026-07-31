# VAT-grouped Invoice Draft Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 50-document pilot produce direction-correct, VAT-grouped, source-traceable journal drafts while keeping UBL primary and repairing the supported text-PDF fallback.

**Architecture:** Intake always supplies purchase/sales direction and canonical UBL party identity validates it. Canonical lines and VAT summaries receive one stable VAT identity, a focused grouping service chooses one real net account per invoice VAT group, and the journal retains line allocations. Text-PDF extraction must recover at least one source-grounded line per declared VAT group before it can complete; UBL/PDF preview and the journal editor expose the same group evidence.

**Tech Stack:** Python 3 dataclasses, `Decimal`, `xml.etree.ElementTree`, existing PDF extraction/provider contracts, PostgreSQL normalized accounting persistence, React/TypeScript, Node tests, Python `unittest`.

## Global Constraints

- UBL/XML is the normal canonical source; text-readable PDF is an uncommon manual fallback.
- Image-only/scanned PDF OCR is outside this slice.
- Ordinary invoice direction is always purchase or sales; no normal `unknown` state is introduced.
- XML supplier/customer VKN evidence wins over a conflicting intake label.
- Same-VAT-group lines default to one semantic net account within one invoice.
- Model uncertainty or wording variation alone does not split a VAT group.
- AI never rewrites source amounts, VAT identity, direction, balance, or canonical line identity.
- Every accepted journal row retains VAT-group and canonical-line allocation evidence.
- Existing dirty-worktree changes must be preserved.
- Documentation work does not authorize commit, push, deploy, corpus deletion, or production reprocessing.

---

## File map

- `backend/app/domain/canonical_invoices.py`: canonical VAT identity fields, group IDs, and validation.
- `backend/app/domain/xml_invoices.py`: UBL line/`TaxSubtotal` tax identity extraction.
- `backend/app/domain/pdf_invoices.py`: supported text-PDF extraction orchestration and targeted missing-group recovery.
- `backend/app/domain/invoice_lines.py`: Turkish monetary/table-row parsing used by PDF extraction.
- `backend/app/domain/vat_accounting_groups.py`: new VAT-group construction and one-account-per-group decision materialization.
- `backend/app/domain/ai_classification.py`: structured VAT-group account-selection request/response.
- `backend/app/domain/matching_simulation.py`: consumes group decisions and builds grouped journal rows.
- `backend/app/persistence/normalized_accounting_repository.py`: persists VAT-group/line allocations and review revisions.
- `backend/app/domain/ubl_invoice_preview.py`: invoice-like VAT distribution rendering and source links.
- `backend/app/workflows/document_processing.py`: exposes group evidence/result status without replacing parser errors with accounting review.
- `backend/scripts/import_private_intake_manifest.py`: requires and propagates corpus invoice direction.
- `frontend/app/workspace-api.js`, `frontend/app/portal-types.ts`, `frontend/app/portal-review-panels.tsx`: map and render group evidence next to the draft.

---

### Task 1: Require real purchase/sales direction at intake

**Files:**
- Modify: `backend/app/domain/document_uploads.py`
- Modify: `backend/scripts/import_private_intake_manifest.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `docs/private-intake-manifest.md`
- Test: `backend/tests/test_document_uploads.py`
- Test: `backend/tests/test_workflow_store.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: manifest row `intake_category`, current client VKN/TCKN, canonical supplier/customer VKN/TCKN.
- Produces: `purchase|sales` base direction plus optional `direction_conflict` evidence.

- [ ] **Step 1: Write failing invoice-intake tests**

```python
def test_invoice_upload_requires_explicit_purchase_or_sales_direction(self):
    with self.assertRaisesRegex(ValueError, "invoice intake_category is required"):
        store_document_content(
            base_dir=self.temp_dir,
            client_id="pilot",
            file_name="invoice.xml",
            document_type="einvoice_xml",
            uploaded_by="test",
            content=b"<Invoice />",
        )

def test_non_invoice_document_keeps_its_existing_default_category(self):
    stored = store_document_content(
        base_dir=self.temp_dir,
        client_id="pilot",
        file_name="bank.csv",
        document_type="bank_statement",
        uploaded_by="test",
        content=b"date,amount",
    )
    self.assertEqual(stored.intake_category, "bank_statement")
```

- [ ] **Step 2: Run the focused test and verify the current purchase fallback fails it**

Run:

```powershell
python -m unittest backend.tests.test_document_uploads
```

Expected: the invoice test fails because `normalize_intake_category` currently defaults a missing invoice to `purchase_invoice`.

- [ ] **Step 3: Make invoice direction explicit without adding `unknown`**

```python
def normalize_intake_category(*, document_type: str, intake_category: str = "") -> str:
    selected = intake_category.strip()

    # Ordinary invoice entry must already know whether the user/provider lane is
    # purchase or sales. Missing direction is an intake contract bug, not a
    # reason to silently classify the invoice as purchase.
    if document_type in {"invoice", "einvoice_xml"} and not selected:
        raise ValueError("invoice intake_category is required")

    selected = selected or DEFAULT_INTAKE_CATEGORY_BY_DOCUMENT_TYPE.get(document_type, "")
    if selected not in ALLOWED_INTAKE_CATEGORIES:
        raise ValueError(f"unsupported intake_category: {selected}")
    return selected
```

- [ ] **Step 4: Add required manifest direction parsing and propagation**

```python
def _invoice_intake_category(row: dict[str, Any], *, document_type: str) -> str:
    if document_type not in {"invoice", "einvoice_xml"}:
        return str(row.get("intake_category") or "")

    direction = str(row.get("intake_category") or "").strip()
    if direction not in {"purchase_invoice", "sales_invoice"}:
        raise ValueError(
            f"invoice manifest row requires purchase_invoice or sales_invoice: "
            f"{row.get('relative_path')}"
        )
    return direction
```

Pass the returned value to both `store_document_content(...)` and
`create_processing_job(...)`. Include it in `imported_documents` summary so the
35/15 preflight can be inspected without opening private sources.

- [ ] **Step 5: Replace direction fallbacks with intake plus canonical identity resolution**

```python
def infer_accounting_direction(invoice, client_profile, *, intended_direction=None):
    intended = _normalize_intended_direction(intended_direction)
    if intended not in {"purchase", "sales"}:
        raise ValueError("invoice processing requires purchase or sales intake direction")

    explicit = _explicit_party_direction(invoice, client_profile)
    if explicit:
        detected, confidence, evidence = explicit

        # Exact supplier/customer identity is canonical document evidence. Use
        # it for the draft, but retain the intake conflict for focused review.
        if detected != intended:
            return detected, confidence, (*evidence, f"intake_conflict_{intended}")
        return detected, confidence, evidence

    # Text PDFs may not expose reliable party tax IDs. The user/provider lane is
    # still a valid direction source, so processing continues in that direction.
    return intended, 88, (f"intake_category_{intended}", "party_identity_unverified")
```

Keep return behavior as a separate flag/subtype instead of creating a third
ordinary direction.

- [ ] **Step 6: Run focused direction/import tests**

Run:

```powershell
python -m unittest backend.tests.test_document_uploads
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_private_intake_manifest_imports_chart_accounts_and_documents
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_safe_direction_conflict_requires_accountant_question
```

Expected: all pass; imported invoice summaries retain explicit categories and exact XML identity conflicts use the canonical direction.

- [ ] **Step 7: Review gate**

Inspect only Task 1 files. Do not delete or reimport corpus data yet. If later
approved as part of the release transaction, commit this independently as
`fix: require invoice direction at intake`.

---

### Task 2: Add canonical VAT identity and line-to-group reconciliation

**Files:**
- Modify: `backend/app/domain/canonical_invoices.py`
- Modify: `backend/app/domain/xml_invoices.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_normalized_invoice_journal.py`

**Interfaces:**
- Produces: `vat_group_id(...)`, enriched `CanonicalInvoiceLine`,
  enriched `CanonicalVatSummaryLine`, and
  `bind_canonical_lines_to_vat_summary(invoice)`.
- Consumed by: Tasks 3, 5, and 6.

- [ ] **Step 1: Write a failing mixed-VAT UBL test**

Create a UBL fixture in the test body with:

- two `%0`, exemption-code `3065` lines;
- three `%20`, standard-category lines;
- matching `TaxSubtotal` records.

Assert:

```python
self.assertEqual(
    [line.vat_group_id for line in parsed.canonical_invoice.line_items],
    ["KDV|E|0|3065", "KDV|E|0|3065", "KDV|S|20|", "KDV|S|20|", "KDV|S|20|"],
)
self.assertEqual(
    parsed.canonical_invoice.vat_summary[1].contributing_line_ids,
    (
        parsed.canonical_invoice.line_items[2].canonical_line_id,
        parsed.canonical_invoice.line_items[3].canonical_line_id,
        parsed.canonical_invoice.line_items[4].canonical_line_id,
    ),
)
```

- [ ] **Step 2: Run the test and verify fields are missing**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_invoice_preserves_vat_identity_and_group_line_links
```

Expected: FAIL because canonical records currently retain only `vat_rate`.

- [ ] **Step 3: Add backward-compatible canonical VAT fields**

```python
@dataclass(frozen=True)
class CanonicalInvoiceLine:
    description: str
    canonical_line_id: str = ""
    source_position: str = ""
    external_line_id: str = ""
    quantity: str = ""
    unit_code: str = ""
    unit_price: str = ""
    taxable_amount: str = ""
    vat_rate: str = ""
    tax_amount: str = ""
    gross_amount: str = ""
    tax_scheme_code: str = ""
    tax_category_code: str = ""
    exemption_reason_code: str = ""
    vat_group_id: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class CanonicalVatSummaryLine:
    rate: str
    taxable_amount: str = ""
    tax_amount: str = ""
    tax_scheme_code: str = ""
    tax_category_code: str = ""
    exemption_reason_code: str = ""
    vat_group_id: str = ""
    contributing_line_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[str, ...] = field(default_factory=tuple)
```

Keep string money/rate fields because the existing canonical payload,
serialization, and persistence contracts use strings.

- [ ] **Step 4: Add one stable VAT-group key helper**

```python
def canonical_vat_group_id(
    *,
    tax_scheme_code: str,
    tax_category_code: str,
    vat_rate: str,
    exemption_reason_code: str = "",
) -> str:
    # Normalize only representation. Never infer a missing exemption/category.
    normalized_rate = _normalized_decimal_text(vat_rate)
    return "|".join(
        (
            tax_scheme_code.strip().upper(),
            tax_category_code.strip().upper(),
            normalized_rate,
            exemption_reason_code.strip().upper(),
        )
    )
```

- [ ] **Step 5: Parse the exact UBL tax identity**

```python
def _tax_identity(element: ET.Element) -> dict[str, str]:
    category = _first_descendant(element, "ClassifiedTaxCategory") or _first_descendant(element, "TaxCategory")
    if category is None:
        return {
            "tax_scheme_code": "",
            "tax_category_code": "",
            "vat_rate": "",
            "exemption_reason_code": "",
        }

    scheme = _first_descendant(category, "TaxScheme")
    return {
        "tax_scheme_code": (
            _first_text_under(scheme, ("TaxTypeCode", "ID")) if scheme is not None else ""
        ),
        "tax_category_code": _first_direct_text(category, "ID"),
        "vat_rate": _first_text_under(category, ("Percent",)),
        "exemption_reason_code": _first_text_under(
            category,
            ("TaxExemptionReasonCode",),
        ),
    }
```

Use this helper for every `InvoiceLine` and `TaxSubtotal`, compute
`vat_group_id`, then bind summary groups to line IDs with the same key.

- [ ] **Step 6: Validate each declared group independently**

Add validation reasons:

```text
vat_group_lines_missing
vat_group_taxable_mismatch
vat_group_tax_mismatch
vat_group_unexpected_lines
```

Do not collapse these into the existing document-level `vat_total_mismatch`;
the worker and preview need the affected group.

- [ ] **Step 7: Run canonical/XML/allocation tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_invoice_preserves_vat_identity_and_group_line_links
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_canonical_invoice_validation_accepts_balanced_line_vat_and_totals
python -m unittest backend.tests.test_normalized_invoice_journal.NormalizedInvoiceJournalSliceTests.test_phase2_allocation_reconciles_mixed_vat_lines_to_journal_components
```

Expected: all pass and old payloads without category fields remain readable.

- [ ] **Step 8: Review gate**

Inspect serialized payload snapshots for backward compatibility. If later
approved, commit independently as `feat: preserve canonical vat group identity`.

---

### Task 3: Render VAT groups in the UBL invoice preview

**Files:**
- Modify: `backend/app/domain/ubl_invoice_preview.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_workflow_store.py`

**Interfaces:**
- Consumes: Task 2 `vat_group_id`, summary amounts, and contributing line IDs.
- Produces: accessible invoice-like HTML with line/group anchors and a visible
  `KDV dagilimi` table.

- [ ] **Step 1: Extend the existing preview test**

Assert that rendered HTML contains:

```text
KDV dağılımı
KDV %0
İstisna 3065
70.000,00
KDV %20
10.000,00
2.000,00
12.000,00
Satırlar 3, 4, 5
```

Also assert every line row has a stable `id="invoice-line-..."` and each badge
links to `#vat-group-...`.

- [ ] **Step 2: Run the preview tests and confirm the current renderer fails**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_invoice_preview_renders_invoice_like_html
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_document_file_returns_rendered_invoice_preview_for_xml
```

Expected: FAIL because the renderer currently ignores `invoice.vat_summary`.

- [ ] **Step 3: Build display rows without changing canonical amounts**

```python
def _vat_distribution_rows(invoice: CanonicalInvoice) -> str:
    rows: list[str] = []
    line_number_by_id = {
        line.canonical_line_id: index
        for index, line in enumerate(invoice.line_items, start=1)
    }

    for group in invoice.vat_summary:
        source_numbers = [
            line_number_by_id[line_id]
            for line_id in group.contributing_line_ids
            if line_id in line_number_by_id
        ]
        gross = _money_sum(group.taxable_amount, group.tax_amount)

        # This is a source VAT group, not an accounting account group.
        label = _vat_group_label(group)
        rows.append(
            _vat_distribution_row_html(
                anchor_id=_safe_anchor(group.vat_group_id),
                label=label,
                source_numbers=source_numbers,
                taxable_amount=group.taxable_amount,
                tax_amount=group.tax_amount,
                gross_amount=gross,
            )
        )
    return "".join(rows)
```

- [ ] **Step 4: Insert the table between source lines and document totals**

Render columns:

```text
KDV grubu | İlgili satırlar | Matrah | KDV | Grup toplamı
```

Use native anchors and visible focus styles. Do not rely on color. For more
than five lines, show `1, 2, 3, 4, 5 +8 satir` while keeping an accessible full
label.

- [ ] **Step 5: Keep technical detail progressive**

Add a `<details>` block only when group validation has a mismatch. It may show
canonical line IDs, UBL source paths, declared/calculated amounts, and the
specific reason code. The normal preview stays compact.

- [ ] **Step 6: Run preview and accessibility checks**

Run the focused Python tests, then manually render a single-rate, mixed-rate,
zero-rate/exempt, and 20-line UBL fixture. Verify keyboard anchors, `%200` zoom,
and narrow iframe layout before marking this task complete.

- [ ] **Step 7: Review gate**

If later approved, commit independently as `feat: show vat distribution in ubl preview`.

---

### Task 4: Make supported text-PDF line recovery a completion requirement

**Files:**
- Modify: `backend/app/domain/invoice_lines.py`
- Modify: `backend/app/domain/pdf_invoices.py`
- Modify: `backend/app/domain/canonical_invoices.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_normalized_invoice_journal.py`

**Interfaces:**
- Consumes: deterministic PDF pages, summary fields, VAT groups, and existing
  `repair|discovery` provider contract.
- Produces: `PdfCanonicalExtractionOutcome` with no missing line group for a
  successful supported text PDF.

- [x] **Step 1: Add failing Turkish-money and duplicate-row tests**

```python
def test_pdf_money_parser_keeps_turkish_thousands_and_decimal(self):
    self.assertEqual(parse_invoice_money("1.641,20"), Decimal("1641.20"))
    self.assertEqual(parse_invoice_money("70.000,00 TL"), Decimal("70000.00"))

def test_pdf_line_extraction_deduplicates_same_source_position_not_equal_amounts(self):
    lines = extract_invoice_lines_from_pages(
        (
            page_with_rows(
                ("page:1,row:4", "Pil", "1.000,00"),
                ("page:1,row:4", "Pil", "1.000,00"),
                ("page:1,row:5", "Aksesuar", "1.000,00"),
            ),
        )
    )
    self.assertEqual([line.description for line in lines], ["Pil", "Aksesuar"])
```

- [x] **Step 2: Add a failing missing-group recovery test**

Create a text PDF fixture/result where `%20` summary matrah is `10000.00`, the
deterministic parser finds `8000.00`, and the discovery provider returns a
source-grounded `2000.00` row. Assert completion only after the group reconciles.

- [x] **Step 3: Introduce an explicit extraction outcome**

```python
@dataclass(frozen=True)
class PdfCanonicalExtractionOutcome:
    invoice: CanonicalInvoice
    missing_vat_group_ids: tuple[str, ...] = ()
    attempts: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_vat_group_ids
```

- [x] **Step 4: Refactor orchestration into commented, testable helpers**

```python
def parse_pdf_invoice(path, *, canonical_extraction_provider=None, canonical_extraction_policy=None, client_identity=None):
    # Pass 1: preserve page text and positions. Later recovery must point back
    # to this evidence; an AI-created row without a source locator is rejected.
    pages, extraction_notes = extract_pdf_pages(path)
    document_text = "\n".join(page.text for page in pages)

    # Pass 2: parse header totals and table lines independently. A repeated
    # amount is not a duplicate unless it repeats the same source position.
    summary = extract_pdf_summary(document_text)
    lines = extract_invoice_lines_from_pages(pages)

    # Pass 3: build VAT groups and determine exactly which declared group is
    # missing source-line coverage or arithmetic reconciliation.
    outcome = reconcile_pdf_canonical(
        pages=pages,
        summary=summary,
        lines=lines,
        extraction_notes=extraction_notes,
    )

    if outcome.missing_vat_group_ids:
        # Pass 4: retry deterministic table recovery only for the affected
        # rate/category/amount gap instead of reparsing the whole invoice.
        recovered = recover_missing_pdf_group_lines(
            pages=pages,
            outcome=outcome,
        )
        outcome = reconcile_pdf_canonical(
            pages=pages,
            summary=summary,
            lines=(*lines, *recovered),
            extraction_notes=(*extraction_notes, "targeted_line_recovery"),
        )

    if outcome.missing_vat_group_ids:
        # Pass 5: source-grounded AI discovery receives the missing groups and
        # known line positions. It observes rows; it cannot calculate totals,
        # choose accounts, or provide authoritative line IDs.
        outcome = discover_missing_pdf_group_lines_with_ai(
            provider=canonical_extraction_provider,
            policy=canonical_extraction_policy,
            document_text=document_text,
            pages=pages,
            outcome=outcome,
            client_identity=client_identity or {},
        )

    if outcome.missing_vat_group_ids:
        # Supported text-PDF completion requires at least one explainable line
        # for every VAT group. Do not convert this parser defect into an empty
        # accountant-review draft or a seller-name-only account decision.
        raise SupportedPdfExtractionError(
            "KDV grubu var fakat bu gruba ait aciklanabilir satir bulunamadi"
        )

    return parsed_invoice_from_canonical(outcome.invoice, pages=pages)
```

The production implementation may keep the public signature and existing
serialization, but the five passes must remain separate testable helpers with
the same responsibilities.

- [x] **Step 5: Preserve AI recovery instead of all-or-nothing rollback**

Change `_maybe_complete_canonical_with_ai` so a source-grounded recovered group
is retained and reconciled group by group. It must not discard every recovered
row merely because a different group or document-level component still needs
focused review. It still rejects missing/duplicate source positions and
AI-modified trusted money.

- [x] **Step 6: Run focused PDF tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_pdf_invoice_populates_canonical_lines_and_vat_summary_from_deterministic_parser
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_pdf_canonical_ai_discovers_missing_rows_with_server_generated_identity
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_pdf_canonical_ai_rejects_discovery_with_duplicate_source_positions
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_pdf_canonical_ai_cannot_overwrite_deterministic_line_money
```

Expected: all pass; the new group-recovery test proves no successful supported
PDF outcome has a missing line group.

- [x] **Step 7: Review gate**

No OCR dependency or image conversion may enter the diff. If later approved,
commit independently as `fix: recover text pdf lines by vat group`.

---

### Task 5: Select one real net account per invoice VAT group

**Files:**
- Create: `backend/app/domain/vat_accounting_groups.py`
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_normalized_invoice_journal.py`

**Interfaces:**
- Consumes: canonical VAT groups, all contributing line descriptions/IDs,
  direction-filtered real chart, client/counterparty context, confirmed rules.
- Produces: `VatGroupAccountDecision` and one materialized line decision per
  canonical line.

- [x] **Step 1: Write the default-homogeneity test**

Use one purchase invoice `%20` group containing battery, accessory, and mould
lines. Make the AI select real account `153.01.002`. Assert:

```python
self.assertEqual(
    {decision["account_code"] for decision in result["line_decisions"]},
    {"153.01.002"},
)
self.assertEqual(
    {decision["decision_origin"] for decision in result["line_decisions"]},
    {"vat_group_default"},
)
```

The AI may return different confidence per wording, but uncertainty must not
split the group.

- [x] **Step 2: Write confirmed-exception and unconfirmed-suggestion tests**

- A matching accountant-confirmed exception rule may place one exact line on a
  different real account.
- A first-seen AI `possible_exception` remains visible review evidence but does
  not silently split the default group.

- [x] **Step 3: Add focused group types**

```python
@dataclass(frozen=True)
class VatAccountingGroup:
    vat_group_id: str
    rate: str
    tax_scheme_code: str
    tax_category_code: str
    exemption_reason_code: str
    taxable_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    lines: tuple[CanonicalInvoiceLine, ...]

    @property
    def line_ids(self) -> tuple[str, ...]:
        return tuple(line.canonical_line_id for line in self.lines)


@dataclass(frozen=True)
class VatGroupAccountDecision:
    vat_group_id: str
    selected_account_code: str
    selected_account_name: str
    covered_line_ids: tuple[str, ...]
    decision_origin: str
    reason: str
    possible_exception_line_ids: tuple[str, ...] = ()

def materialize_group_line_decisions(
    *,
    group: VatAccountingGroup,
    decision: VatGroupAccountDecision,
    confirmed_exceptions: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    results: list[dict[str, object]] = []
    for line in group.lines:
        # Default: every source line inherits the one group account. Different
        # wording or low model confidence is not enough to fragment the draft.
        account_code = decision.selected_account_code
        origin = "vat_group_default"

        # Only an exact, currently matching accountant-confirmed exception may
        # automatically replace the group account in this pilot slice.
        if line.canonical_line_id in confirmed_exceptions:
            account_code = confirmed_exceptions[line.canonical_line_id]
            origin = "confirmed_line_exception"

        results.append(
            {
                "canonical_line_id": line.canonical_line_id,
                "vat_group_id": group.vat_group_id,
                "account_code": account_code,
                "decision_origin": origin,
                "group_reason": decision.reason,
            }
        )
    return tuple(results)
```

- [x] **Step 4: Add a group-scoped AI request**

The structured request contains:

```json
{
  "stage": "vat_group_account",
  "direction": "purchase",
  "vat_group": {
    "vat_group_id": "KDV|S|20|",
    "rate": "20",
    "taxable_amount": "10000.00",
    "line_ids": ["line-1", "line-2", "line-3"],
    "line_descriptions": ["Pil", "Aksesuar", "Kalıp"]
  },
  "client_activity": "İşitme cihazı satışı ve servisi",
  "counterparty": {
    "title": "Pil Tedarik A.S.",
    "tax_id": "1234567890"
  },
  "account_candidates": [
    {"code": "153.01.001", "name": "İşitme cihazları"},
    {"code": "153.01.002", "name": "Pil ve aksesuarlar"}
  ]
}
```

The response selects exactly one current real account and may list possible
exception line IDs for focused review. It cannot rewrite VAT-group membership,
amounts, or canonical IDs.

- [x] **Step 5: Keep accounting sides separate**

```python
def account_roles_for(direction: str) -> dict[str, tuple[str, ...]]:
    if direction == "purchase":
        return {
            # AI semantic choice for net value.
            "net": ("153", "7", "25"),
            # Source VAT plus real chart usability constrains this side.
            "vat": ("191",),
            # Counterparty identity constrains this side.
            "counterparty": ("320",),
        }
    return {
        "net": ("600",),
        "vat": ("391",),
        "counterparty": ("120",),
    }
```

This helper represents candidate roles, not invented account codes. Final
selection always uses real detail accounts from the client's chart.

- [x] **Step 6: Run group-decision tests**

Run the new tests plus:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_simulation_batches_canonical_line_decisions_and_builds_grouped_journal
python -m unittest backend.tests.test_normalized_invoice_journal.NormalizedInvoiceJournalSliceTests.test_phase2_heterogeneous_line_decisions_build_grouped_journal
```

Expected: same-group default decisions remain one account, confirmed exceptions
remain traceable, and every canonical line still receives exactly one decision.

- [x] **Step 7: Review gate**

Review AI authority carefully: deterministic code validates identity,
membership, real-account existence, VAT, and balance but never substitutes a
generic semantic account. If later approved, commit as
`feat: select net accounts by invoice vat group`.

---

### Task 6: Build, persist, and render VAT-grouped journal allocations

**Files:**
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/persistence/normalized_accounting_repository.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `frontend/app/workspace-api.js`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/portal-review-panels.tsx`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_normalized_invoice_journal.py`
- Test: `backend/tests/test_normalized_invoice_journal_postgres.py`
- Test: `frontend/app/workspace-api.test.cjs`
- Test: `frontend/app/portal-preview.test.cjs`

**Interfaces:**
- Consumes: Task 5 materialized line decisions and Task 2 VAT groups.
- Produces: balanced draft rows with `vat_group_id`,
  `contributing_line_ids`, and `allocated_amounts`.

- [x] **Step 1: Write the battery/accessory/mould journal test**

For `%20` purchase lines `2000 + 3000 + 5000`, assert:

```text
153.01.002 debit 10000
191.01.020 debit 2000
320.<supplier> credit 12000
```

Assert the net row retains all three canonical line IDs and the VAT row retains
the `%20` VAT-group ID.

- [x] **Step 2: Add zero-rate food-sales and mixed-rate tests**

- A `%1` food sales group produces one real `600` row, one usable `%1` `391`
  row, and one `120` row.
- A `%0` group produces no invented VAT row.
- `%0` and `%20` groups in the same invoice remain separate.

- [x] **Step 3: Build rows from explicit accounting roles**

```python
def build_vat_grouped_invoice_entry(
    *,
    direction: str,
    groups: tuple[VatAccountingGroup, ...],
    decisions: tuple[VatGroupAccountDecision, ...],
    vat_accounts: Mapping[str, str],
    counterparty_account: str,
) -> JournalEntry:
    lines: list[JournalLine] = []

    for group in groups:
        decision = _decision_for(group.vat_group_id, decisions)

        # Net side: one semantic real account for this invoice VAT group.
        lines.append(
            journal_net_line(
                account_code=decision.selected_account_code,
                amount=group.taxable_amount,
                direction=direction,
                vat_group_id=group.vat_group_id,
                contributing_line_ids=group.line_ids,
            )
        )

        # VAT side: source VAT facts and direction choose the usable 191/391
        # role. Zero tax never creates a fake VAT line.
        if group.tax_amount > Decimal("0.00"):
            lines.append(
                journal_vat_line(
                    account_code=vat_accounts[group.vat_group_id],
                    amount=group.tax_amount,
                    direction=direction,
                    vat_group_id=group.vat_group_id,
                    contributing_line_ids=group.line_ids,
                )
            )

    # Counterparty side: one payable/receivable amount for the invoice.
    lines.append(
        journal_counterparty_line(
            account_code=counterparty_account,
            amount=sum(group.gross_amount for group in groups),
            direction=direction,
        )
    )
    return JournalEntry(lines=tuple(lines))
```

Keep source allowances, charges, prepayment, rounding, withholding, and accepted
`Belge toplam farki - kontrol` behavior in the existing monetary-reconciliation
boundary; do not hide them in the group net amount.

- [x] **Step 4: Persist group allocations**

Extend normalized allocation payloads without breaking existing rows:

```json
{
  "canonical_line_id": "line-1",
  "vat_group_id": "KDV|S|20|",
  "journal_line_no": 1,
  "component": "net",
  "allocated_amount": "2000.00",
  "decision_origin": "vat_group_default"
}
```

Approval still requires complete canonical line/allocation coverage, balanced
debit/credit, valid current chart accounts, and resolved source contradictions.

- [x] **Step 5: Map group evidence to the accountant UI**

Add TypeScript fields:

```ts
export type VatGroupEvidence = {
  vatGroupId: string;
  label: string;
  taxableAmount: string;
  taxAmount: string;
  grossAmount: string;
  contributingLineIds: string[];
  sourceLineNumbers: number[];
};
```

Each draft row exposes its VAT group and source lines. In the primary editor,
show compact copy such as:

```text
Kaynak: KDV %20 · Fatura satırları 3, 4, 5
Grup hesabı: 153.01.002 · Pil, aksesuar ve kalıp
```

Keep raw canonical IDs and provider trace in technical details.

- [x] **Step 6: Keep parser failure, review, and no-posting distinct**

- Missing supported-source line evidence after all recovery attempts:
  `processing_error / line-missing`.
- Populated grouped draft needing accountant confirmation:
  `review_required`.
- Cancelled or fully allowed zero-payable source:
  `no_posting_suggested` with visible reason.

No path may relabel a technical parser failure as a generic empty review draft.

- [x] **Step 7: Run focused persistence/UI tests**

Run:

```powershell
python -m unittest backend.tests.test_normalized_invoice_journal
python -m unittest backend.tests.test_normalized_invoice_journal_postgres
node --test frontend/app/workspace-api.test.cjs frontend/app/portal-preview.test.cjs
```

Expected: complete line/group allocations persist and reload; the primary
review surface exposes group/source evidence; old records still map.

- [x] **Step 8: Review gate**

Inspect tenant keys, revision conflict behavior, approved-reprocess hold, and
export-list eligibility. If later approved, commit as
`feat: persist vat grouped journal evidence`.

---

### Task 7: Rebuild and measure the protected 50-document pilot corpus

**Files:**
- Modify: private ignored intake manifest under `private_samples/`
- Modify: ignored intake summary under `private_samples/`
- Modify: `docs/50-invoice-accountant-reference-runbook.md`
- Test: `backend/tests/test_workflow_store.py`
- Test: `backend/tests/test_normalized_invoice_journal_postgres.py`

**Interfaces:**
- Consumes: verified Tasks 1-6 and authorized pilot tenant/profile/chart data.
- Produces: exactly 35 purchase and 15 sales source records, 44 populated drafts,
  six explained no-posting suggestions, and accountant reference outcomes.

- [ ] **Step 1: Add a manifest preflight command/test**

Preflight must fail before mutation unless:

```text
invoice_count = 50
purchase_count = 35
sales_count = 15
missing_direction_count = 0
duplicate_source_hash_count = 0
xml_party_direction_conflict_count = 0
```

PDF party identity warnings may remain visible when intake direction is explicit;
XML exact party conflicts must be corrected before import.

- [ ] **Step 2: Prepare corrected ignored manifest**

Add `intake_category` to every invoice row. Keep real names, tax IDs, paths, and
source bytes outside Git.

- [ ] **Step 3: Verify recoverability before any deletion**

Use the existing protected-corpus/reset preview and backup posture. Resolve the
exact pilot tenant and document refs. Do not delete anything in documentation
or local-plan execution. Corpus deletion/reimport requires the later approved
release transaction.

- [ ] **Step 4: Reimport and process only after approval**

Preserve client profile, tax certificate, chart accounts, and authorization.
Delete/reimport only the explicitly resolved pilot document set. Run workers to
completion and record source hashes, directions, extraction outcomes,
VAT-group decisions, drafts, and no-posting reasons.

- [ ] **Step 5: Inspect accounting results, not only job completion**

Require:

```text
populated_editable_draft = 44
no_posting_suggested = 6
false_parse_or_persistence_failure = 0
direction_mismatch = 0
missing_vat_group_line = 0
missing_line_decision = 0
missing_allocation = 0
```

Review Cansu expectations (devices/accessories/cargo/utilities/sales and the six
no-posting sources) and Arif PDF Turkish-money/table/group extraction.

- [ ] **Step 6: Capture accountant answer key**

Doğan Abi approves unchanged or corrects every populated draft and confirms
each no-posting reason. Store line/group corrections and explicit learning
confirmation through the normal review path. Freeze only after all 50 have
authoritative outcomes.

- [ ] **Step 7: Quality report**

Measure:

```text
unchanged approval >= 70%
minor non-accounting edit <= 20%
material/unusable correction <= 10%
```

Do not claim accounting quality from green tests alone.

---

### Task 8: Full verification, documentation parity, and release boundary

**Files:**
- Modify after verified implementation:
  `docs/product-plan/00-canonical-decision-register.md`
- Modify after verified implementation:
  `docs/accounting-invoice-automation-plan.md`
- Modify after shipped runtime change:
  `docs/current-handoff.md`

**Interfaces:**
- Consumes: completed Tasks 1-7.
- Produces: local proof, current documentation, and an exact release preflight.

- [ ] **Step 1: Run the stable backend suite**

```powershell
python -m unittest discover -s backend/tests
```

Expected: zero failures. DSN/provider skips must be reported separately.

- [ ] **Step 2: Run frontend tests**

```powershell
node --test frontend/app/*.test.cjs
```

Expected: zero failures.

- [ ] **Step 3: Build frontend**

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
```

Expected: exit code 0.

- [ ] **Step 4: Run formatting/diff proof**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; tracked implementation scope is separated from
unrelated user changes and ignored/private evidence.

- [ ] **Step 5: Self-review against the design**

Check every requirement in
`docs/superpowers/specs/2026-07-31-vat-grouped-invoice-draft-design.md`.
Reject completion if any supported invoice can silently default direction,
complete with a missing VAT-group line, fragment a group on uncertainty, lose
line allocations, or omit VAT distribution from UBL preview.

- [ ] **Step 6: Prepare one release transaction**

Report exact changed files, branch, remote, production target, test/build
results, corpus mutation scope, backup/recovery posture, and material risks.
Because this plan materially expands the earlier patch, obtain a new explicit
approval for `commit + push + deploy + guarded pilot corpus reimport + live
verification`. Stop if scope, target, or risk changes.

- [ ] **Step 7: Update continuity only after shipment**

After successful deployment and live verification, update
`docs/current-handoff.md` with commit/server parity, worker state, 50-document
results, and the next accountant-review step. Never record secrets or private
document contents.
