# Review Note and OCR Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge accountant note and learning instruction into one user-facing decision note, and make invoice/statement OCR policy explicit: no OCR for first live invoice/statement automation, tax certificate OCR stays separate.

**Architecture:** Keep backend compatibility for existing `accountant_note` and `rule_instruction` fields, but make the UI send one `decision_note` value into both fields until storage migration is needed. Add a parser gate for invoice/statement PDF inputs so text PDFs use extracted text, XML remains canonical, and textless/scanned invoices or statements go to review/unsupported without OCR fallback. Tax certificate OCR remains in `tax_certificates.py` only.

**Tech Stack:** FastAPI/Pydantic backend, existing review learning domain, PDF/XML invoice parsers, React portal review UI, Node tests and Python unittest.

---

## File Map

- Modify `frontend/app/portal-review-panels.tsx`: rename review note inputs to one "Karar notu" field and remove the separate visible rule instruction field.
- Modify `frontend/app/upload-api.js`: map `decisionNote` to both `accountant_note` and `rule_instruction` for compatibility.
- Modify `frontend/app/upload-api.test.cjs`: assert the unified note payload.
- Modify `backend/app/api/phase0_schemas.py`: accept optional `decision_note` and normalize note fields.
- Modify `backend/app/services/review_service.py`: use normalized note values when building learning events.
- Modify `backend/app/domain/review_learning.py`: keep both fields in events, with identical value when `decision_note` is supplied.
- Modify `backend/app/domain/pdf_invoices.py`: mark textless PDF invoice parse as `scanned_pdf_unsupported` without OCR.
- Modify `backend/app/workflows/document_processing.py`: remove invoice OCR success telemetry for invoice/statement parse notes.
- Modify `backend/tests/test_phase0_services.py`: cover unified review note event behavior.
- Modify `backend/tests/test_phase0_domain.py`: cover textless PDF gate behavior.
- Modify `docs/open-questions.md`: mark the implementation detail as planned once code lands.

## Task 1: Frontend Payload Contract

**Files:**
- Modify `frontend/app/upload-api.test.cjs`
- Modify `frontend/app/upload-api.js`

- [ ] **Step 1: Write the failing upload API test**

Add or update the existing `storeReviewDecision` test so the caller sends one `decisionNote` and the payload contains both legacy backend fields.

```javascript
test("storeReviewDecision maps decision note to accountant and rule fields", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ stored: true });
  };

  await api.storeReviewDecision({
    apiBaseUrl: "https://example.test",
    clientId: "client-1",
    documentRef: "doc-1",
    action: "approve",
    reviewer: "mali-musavir",
    decisionNote: "Ayni tedarikciden gelen akaryakit gideri 770 hesaba gider.",
    applyToSimilar: true,
  });

  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.decision.accountant_note, "Ayni tedarikciden gelen akaryakit gideri 770 hesaba gider.");
  assert.equal(body.decision.rule_instruction, "Ayni tedarikciden gelen akaryakit gideri 770 hesaba gider.");
});
```

- [ ] **Step 2: Run the targeted frontend test and confirm failure**

Run:

```powershell
node --test frontend/app/upload-api.test.cjs
```

Expected before implementation: the new `decisionNote` value is not mapped into both payload fields.

- [ ] **Step 3: Implement minimal upload API mapping**

In `storeReviewDecision`, normalize the note once:

```javascript
const decisionNote = String(input.decisionNote ?? input.accountantNote ?? input.ruleInstruction ?? "").trim();
```

Then send:

```javascript
accountant_note: decisionNote,
rule_instruction: decisionNote,
```

- [ ] **Step 4: Run the frontend test**

Run:

```powershell
node --test frontend/app/upload-api.test.cjs
```

Expected: all tests in that file pass.

## Task 2: Review Panel UI

**Files:**
- Modify `frontend/app/portal-review-panels.tsx`
- Test `frontend/app/upload-api.test.cjs`

- [ ] **Step 1: Find the current note inputs**

Run:

```powershell
Select-String -Path frontend/app/portal-review-panels.tsx -Pattern "accountant_note|rule_instruction|Duzeltme|not|kural" -Context 2,3
```

- [ ] **Step 2: Replace separate note controls with one field**

Use one controlled value named `decisionNote` or reuse the existing local state that is easiest to keep scoped. The visible label must be `Karar notu`.

```tsx
<label className="field">
  <span>Karar notu</span>
  <textarea
    value={decisionNote}
    onChange={(event) => setDecisionNote(event.target.value)}
    placeholder="Bu karar ayni tip belgelerde nasil uygulanacak?"
  />
</label>
```

- [ ] **Step 3: Keep learning candidate behavior**

When the action is `approve`, `correct_and_approve`, or an equivalent approval action with `applyToSimilar`, pass the same `decisionNote` to the API. When the accountant chooses "Kontrolde kalsin" or "Export disi birak", still store the note as rationale, but do not make automation depend on it.

- [ ] **Step 4: Run frontend checks**

Run:

```powershell
node --test frontend/app/upload-api.test.cjs
cd frontend
npm.cmd run build
```

Expected: tests pass and the frontend build completes.

## Task 3: Backend Compatibility Normalization

**Files:**
- Modify `backend/app/api/phase0_schemas.py`
- Modify `backend/app/services/review_service.py`
- Modify `backend/app/domain/review_learning.py`
- Test `backend/tests/test_phase0_services.py`

- [ ] **Step 1: Write the failing service test**

Add a test that sends `decision_note` and verifies both event fields receive the same value.

```python
def test_review_decision_payload_normalizes_decision_note(self) -> None:
    payload = ReviewDecisionPayload(
        document_ref="doc-1",
        action="approve",
        reviewer="mali-musavir",
        decision_note="Akaryakit belge tipi onayla ogrenme adayidir.",
        apply_to_similar=True,
    )

    event = ReviewService().review_learning_event(payload)

    self.assertEqual(event["accountant_note"], "Akaryakit belge tipi onayla ogrenme adayidir.")
    self.assertEqual(event["rule_instruction"], "Akaryakit belge tipi onayla ogrenme adayidir.")
```

- [ ] **Step 2: Run the targeted backend service test and confirm failure**

Run:

```powershell
python -m unittest backend.tests.test_phase0_services
```

Expected before implementation: `decision_note` is not accepted or not propagated.

- [ ] **Step 3: Add schema field and property normalization**

In `ReviewDecisionPayload`, add:

```python
decision_note: str = ""
```

Add a helper property:

```python
@property
def normalized_decision_note(self) -> str:
    return (self.decision_note or self.accountant_note or self.rule_instruction or "").strip()
```

- [ ] **Step 4: Use normalized value in `ReviewService.review_learning_event`**

Set both fields from the normalized value:

```python
decision_note = payload.normalized_decision_note
accountant_note=decision_note,
rule_instruction=decision_note,
```

- [ ] **Step 5: Run backend service tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_services
```

Expected: tests pass.

## Task 4: Invoice and Statement OCR Gate

**Files:**
- Modify `backend/app/domain/pdf_invoices.py`
- Modify `backend/app/workflows/document_processing.py`
- Test `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Write the failing PDF gate test**

Patch `extract_pdf_text` to simulate a textless PDF and assert there is no OCR note.

```python
def test_textless_pdf_invoice_is_reviewed_without_ocr(self) -> None:
    from pathlib import Path
    from unittest.mock import patch

    from app.domain.pdf_invoices import parse_pdf_invoice

    with patch("app.domain.pdf_invoices.extract_pdf_text", return_value=(1, "", ("pdf_text_empty",))):
        invoice = parse_pdf_invoice(Path("scanned.pdf"))

    self.assertEqual(invoice.suggested_route, "review_queue")
    self.assertIn("scanned_pdf_unsupported", invoice.parse_notes)
    self.assertNotIn("ocr", " ".join(invoice.parse_notes).lower())
```

- [ ] **Step 2: Run the targeted domain test and confirm failure**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Expected before implementation: the new `scanned_pdf_unsupported` note is missing.

- [ ] **Step 3: Add explicit textless PDF branch**

At the top of `parse_pdf_invoice`, after `stripped_text = text.strip()`, add:

```python
if page_count > 0 and not stripped_text:
    return ParsedInvoice(
        file_name=path.name,
        page_count=page_count,
        extracted_text="",
        invoice_no="",
        issue_date="",
        seller_hint="",
        payable_total=None,
        risk_flags=("scanned_pdf_unsupported",),
        suggested_route="review_queue",
        parse_notes=tuple(dict.fromkeys((*extraction_notes, "scanned_pdf_unsupported"))),
    )
```

- [ ] **Step 4: Remove invoice OCR success telemetry**

In `document_processing.py`, delete or narrow the block that emits `ocr_fallback_succeeded` for invoice parse notes. Tax certificate OCR telemetry must stay in the tax certificate flow.

- [ ] **Step 5: Run domain and workflow tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain backend.tests.test_document_upload_api
```

Expected: invoice parsing tests pass; tax certificate OCR tests are unchanged.

## Task 5: Final Verification

- [ ] Run the stable proof set:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
cd frontend
npm.cmd run build
git diff --check
```

- [ ] Manually inspect diff for these acceptance points:
  - UI shows one `Karar notu`.
  - Backend still accepts older `accountant_note` and `rule_instruction` payloads.
  - Text PDF invoice parsing continues without OCR.
  - Textless/scanned invoice PDF becomes review/unsupported.
  - Tax certificate OCR path is untouched.
