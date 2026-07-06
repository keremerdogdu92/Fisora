# UBL Invoice Preview Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show uploaded UBL/XML invoices as a clean, invoice-like preview while keeping XML as the primary accounting extraction source.

**Architecture:** Keep the original XML file unchanged in storage, but add a preview-rendering path that returns sanitized HTML for XML invoices and the original binary file for PDF/images. The HTML renderer uses parsed UBL/canonical invoice fields to build a readable document without exposing technical XML/UBL wording to the accountant.

**Tech Stack:** FastAPI backend, existing `DocumentService`, `xml.etree.ElementTree`, existing `xml_invoices.py` canonical parser, React/Next portal `DocumentPreview`, unittest and node test runner.

---

### Task 1: Backend UBL Preview Renderer

**Files:**
- Create: `backend/app/domain/ubl_invoice_preview.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Write the failing renderer test**

Add a test that builds a small UBL invoice XML and asserts that the renderer returns invoice-like HTML.

```python
def test_ubl_invoice_preview_renders_invoice_like_html(self) -> None:
    from app.domain.ubl_invoice_preview import render_ubl_invoice_preview_html

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>ABC2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-06</cbc:IssueDate>
  <cbc:InvoiceTypeCode>SATIS</cbc:InvoiceTypeCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>Satıcı Ltd Şti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>Alıcı Ltd Şti</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="NIU">2</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="TRY">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>İşitme cihazı bakım seti</cbc:Name></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="TRY">50.00</cbc:PriceAmount></cac:Price>
    <cac:TaxTotal><cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="TRY">100.00</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount>
      <cbc:Percent>20</cbc:Percent>
    </cac:TaxSubtotal></cac:TaxTotal>
  </cac:InvoiceLine>
  <cac:TaxTotal><cac:TaxSubtotal>
    <cbc:TaxableAmount currencyID="TRY">100.00</cbc:TaxableAmount>
    <cbc:TaxAmount currencyID="TRY">20.00</cbc:TaxAmount>
    <cbc:Percent>20</cbc:Percent>
  </cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="TRY">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="TRY">120.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="TRY">120.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""
    html = render_ubl_invoice_preview_html(xml)

    self.assertIn("<!doctype html>", html.lower())
    self.assertIn("ABC2026000000001", html)
    self.assertIn("Satıcı Ltd Şti", html)
    self.assertIn("Alıcı Ltd Şti", html)
    self.assertIn("İşitme cihazı bakım seti", html)
    self.assertIn("120.00", html)
    self.assertNotIn("<Invoice", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_invoice_preview_renders_invoice_like_html
```

Expected: FAIL because `app.domain.ubl_invoice_preview` does not exist.

- [ ] **Step 3: Implement the renderer**

Create `backend/app/domain/ubl_invoice_preview.py` with:

```python
from __future__ import annotations

from html import escape
import xml.etree.ElementTree as ET

from app.domain.xml_invoices import build_xml_canonical_invoice


def _money(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return text or "-"


def _party_block(title: str, name: str, tax_id: str, tax_office: str, address: str) -> str:
    return f"""
      <section class="party">
        <h2>{escape(title)}</h2>
        <strong>{escape(name or "-")}</strong>
        <dl>
          <div><dt>Vergi/TCKN</dt><dd>{escape(tax_id or "-")}</dd></div>
          <div><dt>Vergi dairesi</dt><dd>{escape(tax_office or "-")}</dd></div>
          <div><dt>Adres</dt><dd>{escape(address or "-")}</dd></div>
        </dl>
      </section>
    """


def render_ubl_invoice_preview_html(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    invoice = build_xml_canonical_invoice(root)
    header = invoice.header
    supplier = invoice.supplier_party
    customer = invoice.customer_party
    totals = invoice.totals

    line_rows = []
    for index, line in enumerate(invoice.line_items, start=1):
        line_rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(line.description or '-')}</td>"
            f"<td class='num'>{escape(_money(line.quantity))}</td>"
            f"<td class='num'>{escape(_money(line.unit_price))}</td>"
            f"<td class='num'>{escape(_money(line.taxable_amount))}</td>"
            f"<td class='num'>{escape(_money(line.vat_rate))}</td>"
            f"<td class='num'>{escape(_money(line.tax_amount))}</td>"
            f"<td class='num'>{escape(_money(line.gross_amount))}</td>"
            "</tr>"
        )
    if not line_rows:
        line_rows.append("<tr><td colspan='8' class='empty'>Satır bilgisi bulunamadı.</td></tr>")

    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <style>
    body {{ margin: 0; background: #f3f4f6; color: #111827; font-family: Arial, sans-serif; }}
    .page {{ width: 920px; max-width: calc(100vw - 32px); margin: 16px auto; background: #fff; padding: 28px; box-shadow: 0 1px 8px rgba(15,23,42,.16); }}
    header {{ display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #111827; padding-bottom: 16px; }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 8px; font-size: 13px; color: #374151; }}
    .meta {{ display: grid; grid-template-columns: auto auto; gap: 6px 18px; font-size: 12px; text-align: right; }}
    .parties {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin: 22px 0; }}
    .party {{ border: 1px solid #d1d5db; padding: 14px; }}
    .party strong {{ display: block; min-height: 36px; font-size: 14px; }}
    dl {{ margin: 10px 0 0; display: grid; gap: 6px; font-size: 12px; }}
    dt {{ color: #6b7280; }}
    dd {{ margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; vertical-align: top; }}
    th {{ background: #f9fafb; text-align: left; }}
    .num {{ text-align: right; white-space: nowrap; }}
    .totals {{ margin-left: auto; margin-top: 18px; width: 340px; }}
    .totals div {{ display: flex; justify-content: space-between; border-bottom: 1px solid #e5e7eb; padding: 7px 0; font-size: 13px; }}
    .totals strong {{ font-size: 15px; }}
    .empty {{ text-align: center; color: #6b7280; }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <h1>Fatura</h1>
      <section class="meta">
        <span>Fatura No</span><strong>{escape(header.invoice_no or "-")}</strong>
        <span>Tarih</span><strong>{escape(header.issue_date or "-")}</strong>
        <span>Senaryo</span><strong>{escape(header.profile_id or "-")}</strong>
        <span>Tip</span><strong>{escape(header.invoice_type_code or "-")}</strong>
      </section>
    </header>
    <section class="parties">
      {_party_block("Satıcı", supplier.title, supplier.tax_id, supplier.tax_office, supplier.address)}
      {_party_block("Alıcı", customer.title, customer.tax_id, customer.tax_office, customer.address)}
    </section>
    <table>
      <thead>
        <tr><th>No</th><th>Mal Hizmet</th><th>Miktar</th><th>Birim Fiyat</th><th>Matrah</th><th>KDV %</th><th>KDV</th><th>Toplam</th></tr>
      </thead>
      <tbody>{''.join(line_rows)}</tbody>
    </table>
    <section class="totals">
      <div><span>Mal/Hizmet Toplamı</span><span>{escape(_money(totals.line_extension_amount))}</span></div>
      <div><span>KDV Hariç</span><span>{escape(_money(totals.tax_exclusive_amount))}</span></div>
      <div><span>KDV Dahil</span><span>{escape(_money(totals.tax_inclusive_amount))}</span></div>
      <div><strong>Ödenecek Tutar</strong><strong>{escape(_money(totals.payable_amount))}</strong></div>
    </section>
  </main>
</body>
</html>"""
```

- [ ] **Step 4: Run renderer test**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_invoice_preview_renders_invoice_like_html
```

Expected: PASS.

### Task 2: Preview Endpoint Uses Rendered HTML For XML

**Files:**
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/api/phase0_routes_upload_processing.py`
- Test: `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Write failing backend route test**

Add a test that stores an XML invoice document and calls `/store/document-file/...`, expecting `text/html` preview content rather than raw XML.

```python
def test_document_file_returns_rendered_invoice_preview_for_xml(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        xml_path = base / "documents" / "client-1" / "invoice.xml"
        xml_path.parent.mkdir(parents=True)
        xml_path.write_text(MINIMAL_UBL_XML, encoding="utf-8")
        store = JsonWorkflowStore(base / "store.json")
        service = DocumentService(store=store, document_storage_path=base / "documents")
        store.upsert_workspace_document(
            client_id="client-1",
            document_ref="invoice.xml",
            result={"file_name": "invoice.xml"},
            metadata={
                "document_ref": "invoice.xml",
                "document_type": "einvoice_xml",
                "original_file_name": "invoice.xml",
                "storage_path": str(xml_path),
                "content_type": "application/xml",
            },
        )

        info = service.original_document_file(client_id="client-1", document_ref="invoice.xml", user_id="tester")

        self.assertEqual(info["media_type"], "text/html; charset=utf-8")
        self.assertIn("html", info)
        self.assertIn("Fatura", info["html"])
        self.assertNotIn("<Invoice", info["html"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_document_file_returns_rendered_invoice_preview_for_xml
```

Expected: FAIL because `original_document_file` currently returns the original XML file path.

- [ ] **Step 3: Return HTML preview for XML**

Change `DocumentService.original_document_file` so XML documents return a dict with `html` and `media_type`.

```python
if path.suffix.lower() == ".xml" or "xml" in media_type.lower() or str(document.get("document_type") or "") == "einvoice_xml":
    from app.domain.ubl_invoice_preview import render_ubl_invoice_preview_html

    return {
        "path": path,
        "file_name": file_name,
        "media_type": "text/html; charset=utf-8",
        "html": render_ubl_invoice_preview_html(path.read_text(encoding="utf-8")),
    }
```

Change the FastAPI route to return `HTMLResponse` when `html` exists and `FileResponse` otherwise.

```python
from fastapi.responses import FileResponse, HTMLResponse

if "html" in file_info:
    return HTMLResponse(content=str(file_info["html"]), media_type=str(file_info["media_type"]))
return FileResponse(...)
```

- [ ] **Step 4: Run backend preview tests**

Run:

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_document_file_returns_rendered_invoice_preview_for_xml
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_document_preview_returns_original_pdf
```

Expected: both PASS.

### Task 3: Frontend Keeps The Same Document Preview Surface

**Files:**
- Modify: `frontend/app/portal-review-panels.tsx`
- Test: `frontend/app/portal-preview.test.cjs`

- [ ] **Step 1: Write frontend regression test**

Add an assertion that the preview component does not add visible technical labels or XML-specific download UI.

```js
test("document preview keeps XML invoices inside the same original document frame", () => {
  const source = fs.readFileSync(path.join(process.cwd(), "frontend/app/portal-review-panels.tsx"), "utf8");
  assert.match(source, /original-document-frame/);
  assert.doesNotMatch(source, /XML'den oluşturulmuş/);
  assert.doesNotMatch(source, /Orijinal XML indir/);
});
```

- [ ] **Step 2: Run test**

Run:

```powershell
node --test frontend/app/portal-preview.test.cjs
```

Expected: PASS after confirming the component remains format-neutral.

- [ ] **Step 3: Keep iframe behavior unchanged**

No special XML branch should be added to the UI. The backend returns `text/html`, and existing `isFramePreviewMime` already frames `text/html`.

### Task 4: Counterparty Resolution Audit For UBL

**Files:**
- Modify if needed: `backend/app/domain/matching_simulation.py`
- Modify if needed: `backend/app/domain/counterparty_matching.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add explicit UBL party direction tests**

Add tests proving party identity controls the counterparty side:

```python
def test_ubl_party_resolution_uses_supplier_as_counterparty_for_purchase(self) -> None:
    invoice = parse_xml_invoice(Path("purchase.xml"))
    result = simulate_invoice(invoice, chart_accounts=CHART_WITH_320_SUPPLIER, client_identity={"tax_id": "CUSTOMER_VKN"})
    self.assertEqual(result.accounting_direction, "purchase")
    self.assertEqual(result.counterparty_pool, "320")
    self.assertEqual(result.counterparty_title, "Supplier From XML")


def test_ubl_party_resolution_uses_customer_as_counterparty_for_sale(self) -> None:
    invoice = parse_xml_invoice(Path("sale.xml"))
    result = simulate_invoice(invoice, chart_accounts=CHART_WITH_120_CUSTOMER, client_identity={"tax_id": "SUPPLIER_VKN"})
    self.assertEqual(result.accounting_direction, "sales")
    self.assertEqual(result.counterparty_pool, "120")
    self.assertEqual(result.counterparty_title, "Customer From XML")
```

- [ ] **Step 2: Run tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_supplier_as_counterparty_for_purchase backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_customer_as_counterparty_for_sale
```

Expected: FAIL if current simulation still relies on upload intent or legacy issuer/recipient fields before canonical party identity.

- [ ] **Step 3: Wire canonical party identity as primary evidence**

If the tests fail, update `simulate_invoice` so:

```python
if invoice.canonical_invoice:
    supplier = invoice.canonical_invoice.supplier_party
    customer = invoice.canonical_invoice.customer_party
    if client_identity.tax_id and supplier.tax_id == client_identity.tax_id:
        direction = "sales"
        counterparty = customer
        counterparty_pool = "120"
    elif client_identity.tax_id and customer.tax_id == client_identity.tax_id:
        direction = "purchase"
        counterparty = supplier
        counterparty_pool = "320"
```

Keep title similarity as secondary only. Exact VKN/TCKN match wins.

- [ ] **Step 4: Run full backend proof**

Run:

```powershell
python -m unittest discover -s backend/tests
```

Expected: OK.

### Task 5: End-To-End Verification

**Files:**
- No new files unless tests reveal a gap.

- [ ] **Step 1: Process an XML upload locally**

Use a copied sample XML under the repo storage test area. Confirm the processing result includes canonical line count, validation status, supplier/customer and counterparty fields.

Run:

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_processing_worker_parses_xml_invoice_and_runs_simulation
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run:

```powershell
node --test frontend/app/*.test.cjs
```

Expected: all frontend tests pass.

- [ ] **Step 3: Build frontend**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: Next build succeeds.

- [ ] **Step 4: Render smoke**

Start the app and open a portal document whose source is XML. Verify visually:

- The preview looks like a readable invoice, not raw XML.
- No loud technical XML/UBL label appears in the document panel.
- Supplier, customer, invoice number, date, line rows, KDV and totals are visible.
- The accounting panel still uses XML/canonical extraction fields.

### Completion Criteria

- XML invoices are previewed as readable invoice documents.
- PDF previews still use the original PDF.
- No user-facing "UBL/XML" education or download prompt is added to the normal review surface.
- Counterparty resolution uses exact canonical party identity first.
- Existing backend and frontend proof commands pass.
