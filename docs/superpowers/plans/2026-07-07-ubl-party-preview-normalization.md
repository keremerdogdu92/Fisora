# UBL Party Preview Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make UBL/XML invoice preview and counterparty matching read supplier/customer fields from scoped UBL party paths instead of loose descendant `Name` matches.

**Architecture:** Keep XML as canonical invoice data. Add deterministic UBL party extraction helpers that return title, tax id, tax office, address, and evidence for `AccountingSupplierParty` and `AccountingCustomerParty`; then feed the same canonical party object to preview, parsed invoice fields, and matching. Do not infer product/service meaning from party title.

**Tech Stack:** Python `xml.etree.ElementTree`, FastAPI HTML preview route, existing `CanonicalInvoice` dataclasses, backend `unittest`, existing frontend Node tests.

---

## Source Rules

Use these source-backed rules while implementing:

| Business field | UBL path priority | Fisero target | Notes |
| --- | --- | --- | --- |
| Seller role | `Invoice/cac:AccountingSupplierParty/cac:Party` | `canonical_invoice.supplier_party` and `issuer_*` | UBL role is explicit; do not infer from file name or upload tab. |
| Buyer role | `Invoice/cac:AccountingCustomerParty/cac:Party` | `canonical_invoice.customer_party` and `recipient_*` | This is the buyer/customer party in UBL. |
| Legal title | `Party/PartyLegalEntity/RegistrationName` | `CanonicalInvoiceParty.title` | Highest priority for company title. |
| Display title | `Party/PartyName/Name` | title fallback | Use only if legal title is empty. |
| Person title | `Party/Person/FirstName + FamilyName`, then `Person/Name` if present | title fallback | Needed for individual/TCKN invoices. |
| Tax id | `Party/PartyIdentification/ID`, `Party/PartyTaxScheme/CompanyID`, `Party/PartyLegalEntity/CompanyID` | `CanonicalInvoiceParty.tax_id` | Accept 10 or 11 digits; preserve exact evidence path. |
| Tax office | `Party/PartyTaxScheme/TaxScheme/Name` | `CanonicalInvoiceParty.tax_office` | Reject generic tax scheme names such as `KDV`, `VAT`, `Katma Deger Vergisi`. |
| Address | `Party/PostalAddress` fields and `AddressLine/Line` | `CanonicalInvoiceParty.address` | Join clean parts in stable order. |
| Item description | `InvoiceLine/Item/Name`, then `InvoiceLine/Item/Description` | `CanonicalInvoiceLine.description` | Existing fix should stay scoped to the invoice line item. |
| VAT summary | `TaxTotal/TaxSubtotal/TaxableAmount`, `TaxAmount`, `Percent` | `vat_summary` | Keep document-level and line-level extraction separate. |

## File Structure

- Modify `backend/app/domain/xml_invoices.py`: replace loose party scanning with scoped party extraction helpers.
- Modify `backend/app/domain/ubl_invoice_preview.py`: render canonical party fields with a cleaner layout and no fake empty labels.
- Modify `backend/tests/test_phase0_domain.py`: add party parser regression tests for legal entity, person, tax scheme noise, address, and exact direction.
- Modify `backend/tests/test_workflow_store.py`: verify XML preview uses the improved fields through `DocumentService.original_document_file`.
- Optional modify `frontend/app/styles.css`: only if iframe layout still makes the generated HTML look cramped; keep the preview iframe behavior unchanged.

---

### Task 1: Add Failing Party Extraction Tests

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add a regression test for tax scheme name noise**

Add this test near the existing XML invoice tests:

```python
def test_xml_customer_title_does_not_use_tax_scheme_name(self) -> None:
    from app.domain.xml_invoices import parse_xml_invoice

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>NOISE2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>SATICI A.S.</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID schemeID="VKN">1111111111</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="TCKN">22222222222</cbc:ID></cac:PartyIdentification>
    <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>KDV</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:Person><cbc:FirstName>Ayse</cbc:FirstName><cbc:FamilyName>Yilmaz</cbc:FamilyName></cac:Person>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>1.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "invoice.xml"
        path.write_text(xml, encoding="utf-8")
        invoice = parse_xml_invoice(path)

    self.assertEqual(invoice.recipient_title, "Ayse Yilmaz")
    self.assertEqual(invoice.recipient_tax_id, "22222222222")
    self.assertEqual(invoice.canonical_invoice.customer_party.title, "Ayse Yilmaz")
    self.assertNotEqual(invoice.recipient_title, "KDV")
```

- [ ] **Step 2: Add address and tax office coverage**

```python
def test_xml_party_details_include_address_and_tax_office(self) -> None:
    from app.domain.xml_invoices import parse_xml_invoice

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>ADDR2026000000001</cbc:ID>
  <cbc:IssueDate>2026-07-07</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyLegalEntity><cbc:RegistrationName>MEDIKAL TEDARIK A.S.</cbc:RegistrationName></cac:PartyLegalEntity>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>1111111111</cbc:CompanyID>
      <cac:TaxScheme><cbc:Name>KADIKOY</cbc:Name></cac:TaxScheme>
    </cac:PartyTaxScheme>
    <cac:PostalAddress>
      <cbc:StreetName>Bagdat Cad.</cbc:StreetName>
      <cbc:BuildingNumber>10</cbc:BuildingNumber>
      <cbc:CitySubdivisionName>Kadikoy</cbc:CitySubdivisionName>
      <cbc:CityName>Istanbul</cbc:CityName>
    </cac:PostalAddress>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>ALICI LTD</cbc:Name></cac:PartyName>
    <cac:PartyIdentification><cbc:ID>2222222222</cbc:ID></cac:PartyIdentification>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:InvoiceLine><cac:Item><cbc:Name>Bakim hizmeti</cbc:Name></cac:Item></cac:InvoiceLine>
  <cac:LegalMonetaryTotal><cbc:PayableAmount>1.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "invoice.xml"
        path.write_text(xml, encoding="utf-8")
        invoice = parse_xml_invoice(path)

    supplier = invoice.canonical_invoice.supplier_party
    self.assertEqual(supplier.title, "MEDIKAL TEDARIK A.S.")
    self.assertEqual(supplier.tax_id, "1111111111")
    self.assertEqual(supplier.tax_office, "KADIKOY")
    self.assertIn("Bagdat Cad.", supplier.address)
    self.assertIn("Istanbul", supplier.address)
```

- [ ] **Step 3: Run the focused tests and confirm failure**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_customer_title_does_not_use_tax_scheme_name backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_party_details_include_address_and_tax_office
```

Expected: first test fails with title `KDV`; second test fails because `tax_office` and `address` are empty.

### Task 2: Implement Scoped UBL Party Extraction

**Files:**
- Modify: `backend/app/domain/xml_invoices.py`

- [ ] **Step 1: Add helper dataclass and scoped child utilities**

Add below `TAX_ID_RE`:

```python
GENERIC_TAX_SCHEME_NAMES = {"KDV", "VAT", "KATMA DEGER VERGISI", "KATMA DEGER VERGISI"}


@dataclass(frozen=True)
class XmlPartyDetails:
    title: str = ""
    tax_id: str = ""
    tax_office: str = ""
    address: str = ""
    evidence: tuple[str, ...] = ()
```

Add imports:

```python
from dataclasses import dataclass
```

Add scoped helpers:

```python
def _children(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(root) if _local_name(child.tag) == local_name]


def _child(root: ET.Element, local_name: str) -> ET.Element | None:
    return next((child for child in list(root) if _local_name(child.tag) == local_name), None)


def _text_at(root: ET.Element | None, path: tuple[str, ...]) -> str:
    current = root
    for part in path:
        if current is None:
            return ""
        current = _child(current, part)
    return _text(current)
```

- [ ] **Step 2: Replace loose `_party_details` implementation**

Change `_party_details` to return `XmlPartyDetails` and only read known paths:

```python
def _party_details(root: ET.Element, parent_name: str) -> XmlPartyDetails:
    parent = next((element for element in root.iter() if _local_name(element.tag) == parent_name), None)
    party = _child(parent, "Party") if parent is not None else None
    if party is None:
        return XmlPartyDetails()

    evidence: list[str] = []
    title = _first_party_title(party, evidence=evidence)
    tax_id = _first_party_tax_id(party, evidence=evidence)
    tax_office = _party_tax_office(party, evidence=evidence)
    address = _party_address(party, evidence=evidence)
    return XmlPartyDetails(title=title, tax_id=tax_id, tax_office=tax_office, address=address, evidence=tuple(evidence))
```

Add these helper functions:

```python
def _first_party_title(party: ET.Element, *, evidence: list[str]) -> str:
    for entity in _children(party, "PartyLegalEntity"):
        value = _text_at(entity, ("RegistrationName",))
        if value:
            evidence.append("PartyLegalEntity/RegistrationName")
            return value[:120]
    for name in _children(party, "PartyName"):
        value = _text_at(name, ("Name",))
        if value:
            evidence.append("PartyName/Name")
            return value[:120]
    for person in _children(party, "Person"):
        parts = [
            _text_at(person, ("FirstName",)),
            _text_at(person, ("MiddleName",)),
            _text_at(person, ("FamilyName",)),
        ]
        value = " ".join(part for part in parts if part)
        if value:
            evidence.append("Person/FirstName+FamilyName")
            return value[:120]
    return ""


def _first_party_tax_id(party: ET.Element, *, evidence: list[str]) -> str:
    candidates: list[tuple[str, str]] = []
    for identification in _children(party, "PartyIdentification"):
        candidates.append((_text_at(identification, ("ID",)), "PartyIdentification/ID"))
    for scheme in _children(party, "PartyTaxScheme"):
        candidates.append((_text_at(scheme, ("CompanyID",)), "PartyTaxScheme/CompanyID"))
    for entity in _children(party, "PartyLegalEntity"):
        candidates.append((_text_at(entity, ("CompanyID",)), "PartyLegalEntity/CompanyID"))
    for value, path in candidates:
        digits = re.sub(r"\D", "", value)
        if TAX_ID_RE.match(digits):
            evidence.append(path)
            return digits
    return ""


def _party_tax_office(party: ET.Element, *, evidence: list[str]) -> str:
    for scheme in _children(party, "PartyTaxScheme"):
        value = _text_at(_child(scheme, "TaxScheme"), ("Name",))
        normalized = _ascii_upper(value)
        if value and normalized not in GENERIC_TAX_SCHEME_NAMES:
            evidence.append("PartyTaxScheme/TaxScheme/Name")
            return value[:80]
    return ""


def _party_address(party: ET.Element, *, evidence: list[str]) -> str:
    address = _child(party, "PostalAddress")
    if address is None:
        return ""
    parts = []
    for name in ("StreetName", "BuildingNumber", "CitySubdivisionName", "CityName", "PostalZone"):
        value = _text_at(address, (name,))
        if value:
            parts.append(value)
    for line in _children(address, "AddressLine"):
        value = _text_at(line, ("Line",))
        if value:
            parts.append(value)
    if parts:
        evidence.append("PostalAddress")
    return " / ".join(dict.fromkeys(parts))[:240]
```

Add `_ascii_upper` near the other text helpers:

```python
def _ascii_upper(value: str) -> str:
    return (
        value.upper()
        .replace("İ", "I")
        .replace("İ", "I")
        .replace("Ğ", "G")
        .replace("Ü", "U")
        .replace("Ş", "S")
        .replace("Ö", "O")
        .replace("Ç", "C")
    )
```

- [ ] **Step 3: Update call sites**

Change `_provider_hint`, `build_xml_canonical_invoice`, and `parse_xml_invoice` to use object fields:

```python
supplier = _party_details(root, "AccountingSupplierParty")
customer = _party_details(root, "AccountingCustomerParty")
```

In `build_xml_canonical_invoice`, pass:

```python
supplier_party=CanonicalInvoiceParty(
    title=supplier.title,
    tax_id=supplier.tax_id,
    tax_office=supplier.tax_office,
    address=supplier.address,
    evidence=tuple(f"xml:AccountingSupplierParty/{item}" for item in supplier.evidence) if supplier.evidence else (),
),
customer_party=CanonicalInvoiceParty(
    title=customer.title,
    tax_id=customer.tax_id,
    tax_office=customer.tax_office,
    address=customer.address,
    evidence=tuple(f"xml:AccountingCustomerParty/{item}" for item in customer.evidence) if customer.evidence else (),
),
```

In `parse_xml_invoice`, set:

```python
issuer_title=supplier.title,
issuer_tax_id=supplier.tax_id,
recipient_title=customer.title,
recipient_tax_id=customer.tax_id,
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_customer_title_does_not_use_tax_scheme_name backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_party_details_include_address_and_tax_office backend.tests.test_phase0_domain.Phase0DomainTests.test_xml_invoice_populates_canonical_parties_lines_vat_and_totals backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_supplier_as_counterparty_for_purchase backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_customer_as_counterparty_for_sale
```

Expected: PASS.

### Task 3: Improve The Generated UBL Preview

**Files:**
- Modify: `backend/app/domain/ubl_invoice_preview.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Add preview assertions for address and tax office**

Extend `test_ubl_invoice_preview_renders_invoice_like_html` or add a separate preview test with `PostalAddress` and `PartyTaxScheme`. Assert:

```python
self.assertIn("KADIKOY", html)
self.assertIn("Bagdat Cad.", html)
self.assertNotIn(">KDV</strong>", html)
```

- [ ] **Step 2: Make empty party details visually quiet**

Change `_party_block` so it only renders rows that have values:

```python
def _detail_row(label: str, value: str) -> str:
    if not str(value or "").strip():
        return ""
    return f"<div><dt>{escape(label)}</dt><dd>{escape(str(value).strip())}</dd></div>"
```

Then use:

```python
details = (
    _detail_row("Vergi/TCKN", tax_id)
    + _detail_row("Vergi dairesi", tax_office)
    + _detail_row("Adres", address)
)
```

Keep `title` fallback as `-`, but do not show fake rows full of `-`.

- [ ] **Step 3: Run preview tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_invoice_preview_renders_invoice_like_html backend.tests.test_workflow_store.WorkflowStoreTests.test_document_file_returns_rendered_invoice_preview_for_xml
```

Expected: PASS.

### Task 4: Lock Counterparty Matching To Canonical Party Direction

**Files:**
- Modify if needed: `backend/app/domain/matching_simulation.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add an explicit noisy-title matching regression**

Add a case where customer title would be `KDV` under the old parser but direction must still be exact by tax id:

```python
def test_ubl_counterparty_matching_uses_tax_id_even_when_party_has_tax_scheme_name(self) -> None:
    # Reuse the noisy XML shape from test_xml_customer_title_does_not_use_tax_scheme_name.
    # Client tax id is customer TCKN, so direction must be purchase and counterparty must be supplier.
    self.assertEqual(result.accounting_direction, "purchase")
    self.assertEqual(result.suggested_counterparty_account, "320.1111111111")
    self.assertEqual(result.counterparty_title, "SATICI A.S.")
```

- [ ] **Step 2: Confirm existing matching logic still passes**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_supplier_as_counterparty_for_purchase backend.tests.test_phase0_domain.Phase0DomainTests.test_ubl_party_resolution_uses_customer_as_counterparty_for_sale
```

Expected: PASS. If it fails, update `_counterparty_title`, `_counterparty_tax_identifier`, and `_counterparty_match_for_invoice` to prefer `invoice.canonical_invoice.supplier_party/customer_party` over legacy flat fields.

### Task 5: Verification Gate

**Files:**
- No new files unless tests expose a gap.

- [ ] **Step 1: Run backend test suite**

Run:

```powershell
python -m unittest discover -s backend/tests
```

Expected: OK.

- [ ] **Step 2: Run frontend contract tests**

Run:

```powershell
node --test frontend/app/*.test.cjs
```

Expected: OK.

- [ ] **Step 3: Build frontend**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 4: Whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output.

## Completion Criteria

- `AccountingSupplierParty` and `AccountingCustomerParty` are the only source of seller/buyer role.
- Party title never comes from generic descendant `Name` such as `TaxScheme/Name=KDV`.
- Company title, individual name, VKN/TCKN, tax office, and address are extracted with evidence.
- XML preview is readable and does not show rows full of `-`.
- Counterparty matching remains exact: client in supplier means sales/120 customer; client in customer means purchase/320 supplier.
- Product/service classification still requires `InvoiceLine/Item` evidence.
