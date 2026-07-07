# Zirve Field Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the manual Zirve import/mapping export with real Zirve field testing and turn the current unverified mapping CSV into a documented first-live export path.

**Implementation status:** Technical preparation completed on 2026-07-07. The `zirve_mapping_csv` header/BOM/semicolon contract is covered by tests, adapter metadata remains `field_test_pending`, a field-test runbook was added, and a local ignored synthetic sample was generated. The portal export screen can now select `zirve_mapping_csv` and call the backend workspace export-package route to create a downloadable field-test package. Real accountant-side Zirve import is still required before marking the adapter verified.

**Architecture:** Keep `zirve_mapping_csv` as the primary candidate because Zirve column mapping is manually configured by the accountant. Add a field-test fixture/export checklist, record mapping results in docs, and only flip adapter status to verified after a successful accountant-side import. No direct Zirve API or document upload is added.

**Tech Stack:** Existing Python journal exporters, export adapter metadata, CSV semicolon output, portal readiness labels, docs-based field test record, Python unittest and Node tests.

---

## File Map

- Modify `backend/app/domain/exporters.py`: keep or adjust `ZIRVE_MAPPING_COLUMNS` after field-test feedback.
- Modify `backend/app/domain/export_adapters.py`: update `zirve_mapping_csv` notes and verification status only after test evidence.
- Modify `backend/app/services/export_service.py`: include adapter notes in package metadata.
- Modify `backend/tests/test_phase0_domain.py`: assert mapping CSV columns and semicolon encoding.
- Modify `frontend/app/pilot-readiness.js`: keep "format validation required" until adapter status is verified.
- Modify `frontend/app/*.test.cjs`: cover readiness label if existing tests own it.
- Modify `docs/zirve-validation-matrix.md`: record actual Zirve import steps, column mapping, result, and correction list.
- Create `docs/zirve-field-test-runbook.md`: operator checklist for testing in Zirve.
- Add sample generated file under an ignored/export output path during execution; do not commit private accountant data.

## Task 1: Lock Current Mapping CSV Contract

**Files:**
- Modify `backend/tests/test_phase0_domain.py`
- Verify `backend/app/domain/exporters.py`

- [ ] **Step 1: Write or update exporter test**

Add a test that checks exact headers and semicolon delimiter.

```python
def test_zirve_mapping_csv_headers_are_manual_mapping_contract(self) -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.domain.exporters import ZIRVE_MAPPING_COLUMNS, export_zirve_mapping_csv
    from app.domain.journal_entries import JournalEntry, JournalLine

    entry = JournalEntry(
        entry_id="entry-1",
        client_id="client-1",
        entry_date="2026-07-01",
        entry_type="purchase_invoice",
        description="Test fis",
        source_document="doc-1",
        lines=(
            JournalLine(account_code="770.01", description="Gider", debit=100, credit=0, document_ref="doc-1"),
            JournalLine(account_code="320.01", description="Tedarikci", debit=0, credit=100, document_ref="doc-1"),
        ),
    )

    with TemporaryDirectory() as tmp:
        path = export_zirve_mapping_csv([entry], Path(tmp) / "zirve.csv")
        text = path.read_text(encoding="utf-8-sig")

    header = text.splitlines()[0]
    self.assertEqual(header, ";".join(ZIRVE_MAPPING_COLUMNS))
    self.assertIn("hesap_kodu;evrak_tarihi;evrak_no;belge_turu;aciklama;borc;alacak", header)
```

- [ ] **Step 2: Run the targeted domain test**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Expected: current export columns are either confirmed or the test reveals the exact mismatch.

- [ ] **Step 3: Keep output UTF-8-SIG and semicolon**

If the test fails due to delimiter or encoding, update only `export_zirve_mapping_csv`. Do not change accounting values in this task.

- [ ] **Step 4: Run the domain test again**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Expected: mapping CSV contract is stable.

## Task 2: Create Zirve Field Test Runbook

**Files:**
- Create `docs/zirve-field-test-runbook.md`
- Modify `docs/zirve-validation-matrix.md`

- [ ] **Step 1: Create runbook with exact test steps**

Use this structure:

```markdown
# Zirve Field Test Runbook

## Test Input

- Export adapter: `zirve_mapping_csv`
- File type: CSV, UTF-8-SIG, semicolon delimiter
- Documents: one purchase invoice, one sales invoice, one bank transaction if available

## Zirve Manual Mapping

- `hesap_kodu`: Zirve account code field
- `evrak_tarihi`: document/voucher date field
- `evrak_no`: document number field
- `belge_turu`: document type or voucher type field
- `aciklama`: line description field
- `borc`: debit amount field
- `alacak`: credit amount field
- `vkn_tckn`: tax id field if Zirve screen accepts it
- `odeme_sekli`: payment method field if Zirve screen accepts it
- `fis_turu`: voucher type field if separate from document type
- `satir_no`: optional line order field
- `kaynak_belge`: optional audit/source reference field

## Pass Criteria

- Zirve accepts the file with manual column mapping.
- Debit and credit totals match the Fisora export.
- Voucher date, document number, account code, debit, credit, and description land in the expected Zirve fields.
- Optional fields are either accepted or documented as ignored.

## Result Log

| Date | Zirve version | Tester | Result | Required changes |
| --- | --- | --- | --- | --- |
```

- [ ] **Step 2: Update validation matrix**

In `docs/zirve-validation-matrix.md`, point the `zirve_mapping_csv` row to the runbook and keep status `field_test_pending`.

- [ ] **Step 3: Run markdown diff check**

Run:

```powershell
git diff --check -- docs/zirve-field-test-runbook.md docs/zirve-validation-matrix.md
```

Expected: no whitespace errors.

## Task 3: Export Package Metadata

**Files:**
- Modify `backend/app/services/export_service.py`
- Modify `backend/app/domain/export_adapters.py`
- Test `backend/tests/test_phase0_services.py`

- [ ] **Step 1: Add metadata test**

```python
def test_export_package_exposes_zirve_mapping_field_notes(self) -> None:
    service = ExportService()
    # Use the existing test fixture style in this file to create a package with export_type="zirve_mapping_csv".
    package = service.build_export_package(client_id="client-1", export_type="zirve_mapping_csv")

    adapter = package["adapter"]
    self.assertEqual(adapter["validation_status"], "field_test_pending")
    self.assertFalse(adapter["verified_in_zirve"])
    self.assertTrue(any("manual column mapping" in note.lower() for note in adapter["field_mapping_notes"]))
```

- [ ] **Step 2: Run service tests and confirm current behavior**

Run:

```powershell
python -m unittest backend.tests.test_phase0_services
```

Expected: test either passes from current metadata or identifies the exact field missing from package response.

- [ ] **Step 3: Add missing metadata only**

If needed, include `field_mapping_notes`, `validation_status`, and `verified_in_zirve` in export package response. Do not mark verified yet.

- [ ] **Step 4: Run service tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_services
```

Expected: metadata is visible to portal/readiness.

## Task 4: Portal Readiness Label

**Files:**
- Modify `frontend/app/pilot-readiness.js`
- Test matching `frontend/app/*.test.cjs` file if one covers readiness

- [ ] **Step 1: Search readiness tests**

Run:

```powershell
Select-String -Path frontend/app/*.test.cjs -Pattern "zirveLabel|Format dogrulamasi|verified_in_zirve|field_test_pending"
```

- [ ] **Step 2: Add or update readiness test**

```javascript
test("pilot readiness labels Zirve mapping as field test pending", () => {
  const result = buildPilotReadinessViewModel({
    commercial: { zirve_import_claim: "unverified_until_field_test" },
    readiness: {},
  });

  assert.equal(result.zirveLabel, "Format dogrulamasi gerekli");
});
```

Use the exact exported helper names already present in the readiness test file.

- [ ] **Step 3: Run frontend tests**

Run:

```powershell
node --test frontend/app/*.test.cjs
```

Expected: readiness still communicates that field validation is pending.

## Task 5: Execute Field Test With Accountant

**Files:**
- Generated local export package under configured export path
- Modify `docs/zirve-validation-matrix.md`
- Modify `docs/zirve-field-test-runbook.md`

- [ ] **Step 1: Generate a test package**

Use the app route or existing export flow for one test client with approved draft entries. Capture:
  - export adapter
  - generated file name
  - entry count
  - debit total
  - credit total

- [ ] **Step 2: Accountant maps columns in Zirve**

Record the actual Zirve screen labels next to the CSV columns in the runbook.

- [ ] **Step 3: Record import result**

If import fails, record the exact failing column, error message, and required CSV adjustment.

If import succeeds, record the date, tester, Zirve version, and pass criteria result.

- [ ] **Step 4: Update adapter status only after success**

After a successful field test, change:

```python
verified_in_zirve=True
validation_status="verified"
```

for `zirve_mapping_csv` only.

- [ ] **Step 5: Run final verification**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain backend.tests.test_phase0_services
node --test frontend/app/*.test.cjs
git diff --check
```

- [ ] Acceptance:
  - We know which CSV column maps to which Zirve field.
  - Zirve import either has a concrete correction list or verified status.
  - No claim says "verified" before real field evidence.
  - Documents themselves are not uploaded to Zirve.
