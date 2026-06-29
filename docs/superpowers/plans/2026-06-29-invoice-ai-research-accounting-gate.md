# Invoice AI Research Accounting Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make invoice posting work across many taxpayers by using deterministic accounting rules first, AI classification second, Tavily/global research third, and accountant learning last, while always producing a draft voucher and keeping export gated by confidence.

**Architecture:** The invoice worker keeps one decision chain: parse invoice, infer direction, apply legal/accounting hard rules, classify line identity, optionally ask AI, optionally use cached/Tavily research, then build or rebuild the voucher with account-family guards. `matching_simulation.py` remains the posting authority; `document_processing.py` remains orchestration; product identity, AI gate, and research cache rules are small domain helpers.

**Tech Stack:** Python domain services and unittest backend tests; existing OpenAI/Groq-compatible AI providers; existing Tavily research harness; existing JSON/Postgres workflow stores; existing portal review UI.

---

## Accepted Decisions

- AI should run before Tavily because the model may already know common brands and models.
- AI must be asked in a constrained way: no internet claim, no invented account code, category plus confidence plus whether external research is needed.
- Tavily runs at most once per document.
- The researched phrase is global cache data. The same brand/model/phrase should be reused across clients unless an accountant override exists.
- A voucher draft should always be produced when core totals and direction are available, even if `export_status=review_required`.
- Mixed VAT must be solved line-by-line where possible: hearing aid device lines use `%0 / 3065`, taxable accessory/battery/charger lines keep their VAT. If line split cannot be trusted, keep a gross balanced review draft.
- Accountant can explain in natural language. AI can turn that explanation into a candidate rule, but the rule must be previewed and review-gated.
- The engine must generalize across taxpayer types, not only hearing-aid firms.

## Implementation Progress

- 2026-06-29: Phase 1-5 backend behavior implemented and covered by backend tests.
- 2026-06-29: Phase 6 backend behavior implemented: review payload accepts accountant notes, enrichment stores a natural-language rule candidate, and candidate rules do not auto-apply unless the accountant explicitly uses `suggest_for_similar`.
- 2026-06-29: Phase 7 portal behavior implemented: the voucher line editor is first, decision-chain evidence is secondary, and correction note plus rule instruction are stored with the same review decision payload.
- 2026-06-29: Full local proof passed before release: backend unittest suite, frontend node tests, Next production build, and whitespace check.
- Remaining after live release: Phase 8 multi-taxpayer validation matrix with real private samples and selected live smoke cases.

## Phase 0: Baseline Guard

**Files:**
- Read: `backend/app/domain/matching_simulation.py`
- Read: `backend/app/workflows/document_processing.py`
- Read: `backend/app/domain/ai_classification.py`
- Read: `backend/app/domain/research_harness.py`
- Read: `backend/app/domain/learning_rules.py`
- Read: `backend/app/domain/learning_intelligence.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_research_harness.py`
- Test: `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Capture current status**

Run:

```powershell
git status --short
python -m unittest discover -s backend/tests
git diff --check
```

Expected:

```text
backend tests pass before new implementation starts
git diff --check has no whitespace errors
```

- [ ] **Step 2: Preserve existing in-flight changes**

Do not revert current uncommitted account-plan work. If the branch still contains the 2026-06-29 account-plan edits, build on them and keep tests passing.

## Phase 1: AI Gate Before Tavily

**Files:**
- Create: `backend/app/domain/invoice_ai_gate.py`
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add a deterministic AI gate model**

Create `backend/app/domain/invoice_ai_gate.py` with this responsibility:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvoiceAiGateDecision:
    needs_ai: bool
    reason: str
    allow_ai_account_override: bool
    allow_research_after_ai: bool


def invoice_ai_gate(
    *,
    product_category: str,
    product_confidence: int,
    business_relation: str,
    account_treatment: str,
    line_hint: str,
    hard_rule_reason_codes: tuple[str, ...] = (),
) -> InvoiceAiGateDecision:
    if hard_rule_reason_codes:
        return InvoiceAiGateDecision(False, "hard_rule_applied", False, False)
    normalized = " ".join(str(line_hint or "").lower().split())
    vague_terms = {"bedel", "hizmet", "mal", "urun", "muhtelif", "islem"}
    token_count = len(normalized.split())
    looks_like_brand_model = token_count <= 5 and bool(normalized)
    vague = normalized in vague_terms or any(normalized == term for term in vague_terms)
    if product_category in {"", "bilinmeyen", "not_assessed"}:
        return InvoiceAiGateDecision(True, "unknown_product_category", True, True)
    if product_confidence < 70:
        return InvoiceAiGateDecision(True, "low_product_confidence", True, True)
    if business_relation == "weak_match":
        return InvoiceAiGateDecision(True, "weak_business_match", True, True)
    if account_treatment == "manual_review":
        return InvoiceAiGateDecision(True, "manual_review_treatment", True, True)
    if vague or looks_like_brand_model:
        return InvoiceAiGateDecision(True, "brand_model_or_vague_line", True, True)
    return InvoiceAiGateDecision(False, "static_confident", False, False)
```

- [ ] **Step 2: Extend AI schema for research handoff**

In `backend/app/domain/ai_classification.py`, extend `AiProviderClassification` and `AiClassificationResult` with:

```python
product_identity: str = ""
needs_research: bool = False
research_query: str = ""
```

Extend `AiClassificationRequest.to_schema_payload()` output schema with:

```python
"product_identity": {"type": "string", "maxLength": 160},
"needs_research": {"type": "boolean"},
"research_query": {"type": "string", "maxLength": 160},
```

Validation rule:

```python
product_identity = str(payload.get("product_identity") or "").strip()[:160]
needs_research = bool(payload.get("needs_research"))
research_query = str(payload.get("research_query") or "").strip()[:160]
```

- [ ] **Step 3: Tighten AI prompt**

In `backend/app/domain/openai_provider.py`, update invoice classification instructions to include:

```text
Internet aramasi yapma veya kaynak biliyormus gibi davranma.
Egitiminden biliyorsan marka/modelin urun kategorisini soyle.
Emin degilsen needs_research=true ve kisa research_query don.
Yeni hesap kodu uydurma; sadece verilen adaylardan sec.
Kanuni KDV ve hesap ailesi kurallarini ezme.
```

- [ ] **Step 4: Use gate before product classifier call**

In `backend/app/domain/matching_simulation.py`, compute gate after static `assess_business_relevance()`. Only call `product_classifier.classify()` when `gate.needs_ai` is true, except existing explicit API benchmark paths.

Expected new payload fields on `SimulatedInvoiceResult`:

```python
ai_gate_reason: str
ai_research_requested: bool
ai_research_query: str
ai_product_identity: str
```

- [ ] **Step 5: Add tests**

Add tests in `backend/tests/test_phase0_domain.py`:

```python
def test_invoice_ai_gate_skips_known_kargo_line() -> None:
    # kargo line with high static confidence should not call provider

def test_invoice_ai_gate_calls_ai_for_brand_model_only_line() -> None:
    # "RLi 20" or "Rexton RLi 20" should call provider before Tavily

def test_ai_response_can_request_research_without_overriding_export() -> None:
    # provider returns needs_research true; result carries ai_research_requested
```

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Expected: all tests pass.

## Phase 2: Account-Family Guard and Always-Draft Behavior

**Files:**
- Create: `backend/app/domain/account_guardrails.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add account-family guard**

Create `backend/app/domain/account_guardrails.py`:

```python
from __future__ import annotations


def account_family(code: str) -> str:
    return str(code or "").strip().split(".")[0]


def account_allowed_for_treatment(code: str, treatment: str, direction: str) -> bool:
    family = account_family(code)
    if not family:
        return False
    if direction == "sales":
        return family in {"600", "601", "602"}
    if treatment == "stock_or_cogs":
        return family in {"153", "150", "151", "152"}
    if treatment == "expense":
        return family in {"740", "750", "760", "770", "780"}
    if treatment == "non_deductible_review":
        return family == "689"
    if treatment == "fixed_asset_review":
        return family.startswith("25")
    return family in {"153", "740", "750", "760", "770", "780", "689"}
```

- [ ] **Step 2: Reject AI account if family is wrong**

In `matching_simulation.py`, replace direct use of `ai_suggested_account_code` with:

```python
guarded_ai_account = (
    ai_suggested_account_code
    if account_allowed_for_treatment(ai_suggested_account_code, relevance.account_treatment, direction)
    else ""
)
```

Use `guarded_ai_account` before deterministic fallback.

- [ ] **Step 3: Always create a draft**

Keep `export_status=review_required` for weak or low-confidence cases, but produce a balanced draft when amount and direction are available:

```text
review draft is allowed
export-ready is not allowed
```

If VAT split cannot be allocated line-by-line, keep existing `gross_balanced_needs_vat_split` behavior and show review reason.

- [ ] **Step 4: Add tests**

Add tests:

```python
def test_ai_cannot_route_stock_line_to_expense_account() -> None:
    # AI suggests 770 for pil; result keeps 153 and marks ai_account_family_rejected

def test_low_confidence_invoice_still_builds_review_draft() -> None:
    # unknown product creates draft_lines but export_status review_required
```

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

## Phase 3: AI Then Global Tavily Research Cache

**Files:**
- Create: `backend/app/domain/product_research_cache.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/domain/research_harness.py`
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Test: `backend/tests/test_research_harness.py`
- Test: `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Normalize global phrase key**

Create `backend/app/domain/product_research_cache.py`:

```python
from __future__ import annotations

import re


def normalize_product_research_key(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())[:120]
```

- [ ] **Step 2: Use AI research query first**

In `document_processing.py`, research candidate order becomes:

```python
result.get("ai_research_query")
result.get("ai_product_identity")
result.get("product_line_hint")
document.get("original_file_name")
```

- [ ] **Step 3: Use global cache before Tavily**

Before calling `harness.research_brand()`, compute normalized key and call existing `get_brand_research_profile(key)`. If present, use it without Tavily call.

- [ ] **Step 4: Enforce one Tavily call per document**

Use existing `FISORA_RESEARCH_MAX_PER_DOCUMENT`, default `1`. If AI requests research for multiple lines, pick the highest-impact unknown phrase first and log skipped phrases.

- [ ] **Step 5: Store global profile**

When Tavily returns a profile, store it through existing `save_brand_research_profile(brand_name=key, profile=profile)`. Keep accountant override profiles dominant over provider refresh.

- [ ] **Step 6: Add tests**

Add tests:

```python
def test_ai_research_query_is_used_before_raw_line_for_tavily() -> None:
    # AI says research_query="Rexton RLi 20"; Tavily receives that phrase

def test_global_brand_model_cache_prevents_second_tavily_call() -> None:
    # two clients with same phrase; second uses stored profile

def test_one_research_call_per_document_limit_is_enforced() -> None:
    # multiple unknown phrases; one provider call
```

Run:

```powershell
python -m unittest backend.tests.test_research_harness backend.tests.test_workflow_store
```

## Phase 4: Research Result Rebuilds Posting Decision

**Files:**
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/workflows/document_processing.py`
- Test: `backend/tests/test_research_harness.py`
- Test: `backend/tests/test_phase0_domain.py`

- [ ] **Step 1: Add classification override to simulation**

Allow `simulate_invoice()` to accept a `classification_override: ProductClassification | None = None`.

When provided, use it in `assess_business_relevance()` before account selection and draft construction.

- [ ] **Step 2: After research, rebuild the draft**

In `document_processing.py`, after a successful research profile:

```python
classification_override = ProductClassification(
    raw_line=raw_line,
    category=profile["product_category"],
    confidence=profile["accounting_impact_confidence"],
    evidence=("research_profile",),
)
```

Re-run `simulate_invoice()` with the same invoice, selection, client profile, counterparty match, and classification override.

- [ ] **Step 3: Preserve research metadata**

Merge metadata back into the rebuilt result:

```text
research_profile
research_confidence
accounting_impact_confidence
research review reasons
pipeline events
AI explanation
```

- [ ] **Step 4: Add tests**

Add tests:

```python
def test_research_profile_rebuilds_unknown_brand_model_as_stock() -> None:
    # unknown model becomes hearing device category; draft uses 153/600.00.3065 as appropriate

def test_low_accounting_impact_research_keeps_review_required_with_draft() -> None:
    # draft exists, export_status review_required
```

Run:

```powershell
python -m unittest backend.tests.test_research_harness backend.tests.test_phase0_domain
```

## Phase 5: Mixed VAT Line-Level Resolution

**Files:**
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/domain/vat_split_learning.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Keep line-level VAT if extracted**

For sales invoices with multiple VAT rates or line details:

```text
hearing aid device line -> zero VAT revenue account
battery/accessory/charger line -> normal taxable revenue and 391
unknown taxable line -> taxable review line
```

- [ ] **Step 2: Do not mark whole invoice wrong when only accessory is taxable**

`hearing_device_vat_should_be_zero` should trigger only when a hearing-device line itself carries VAT or when the parser cannot separate taxable accessory lines from device lines.

- [ ] **Step 3: Keep review draft if unsolved**

If line allocation is uncertain:

```text
draft_quality = gross_balanced_needs_vat_split
export_status = review_required
draft_lines exist
```

- [ ] **Step 4: Add tests**

Add tests:

```python
def test_mixed_device_and_battery_sales_keeps_device_zero_and_battery_taxable() -> None:
    # device line posts 600.00.3065; battery line posts 600.20 and 391.20

def test_device_line_with_own_vat_requires_review() -> None:
    # hearing device line carrying VAT triggers hearing_device_vat_should_be_zero

def test_unsolved_mixed_vat_keeps_balanced_review_draft() -> None:
    # totals known but line split unclear
```

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain backend.tests.test_workflow_store
```

## Phase 6: Natural-Language Accountant Rule Builder

**Files:**
- Create: `backend/app/domain/natural_language_rule_builder.py`
- Modify: `backend/app/domain/learning_intelligence.py`
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_phase0_services.py`

- [x] **Step 1: Accept accountant explanation**

Extend review payload with:

```python
accountant_note: str = ""
rule_instruction: str = ""
```

- [x] **Step 2: Convert note to candidate rule**

Create `natural_language_rule_builder.py` that returns a structured candidate:

```python
{
    "scope": "global_product_phrase" | "client_only" | "counterparty" | "vat_split",
    "match_phrase": "...",
    "product_category": "...",
    "account_treatment": "...",
    "suggested_account_code": "...",
    "requires_review": True,
    "reason": "..."
}
```

The first implementation can be deterministic for common phrases and AI-assisted only when provider is configured.

- [x] **Step 3: Never auto-activate vague rules**

Rules from natural language are saved as candidates unless accountant explicitly chooses `suggest_for_similar`.

- [x] **Step 4: Add tests**

Add tests:

```python
def test_accountant_note_creates_global_product_phrase_rule_candidate() -> None:
    # "Rexton cihazdır stoktan çıkar" becomes candidate, not auto export

def test_vague_accountant_note_requires_manual_rule_review() -> None:
    # "bunu böyle yap" creates no active rule
```

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain backend.tests.test_phase0_services
```

## Phase 7: Portal Visibility

**Files:**
- Modify: `frontend/app/workspace-api.js`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/features/documents/*`
- Modify: `frontend/app/portal-review-panels.tsx`
- Test: `frontend/app/workspace-api.test.cjs`

- [ ] **Step 1: Expose decision chain**

Show compact fields:

```text
Kural
AI
Araştırma
Müşavir öğrenmesi
Export durumu
```

- [ ] **Step 2: Show why review is needed**

Display:

```text
AI güveni düşük
Araştırma muhasebe etkisi düşük
KDV satır ayrımı çözülemedi
Hesap ailesi uyuşmadı
```

- [ ] **Step 3: Add tests**

Run:

```powershell
node --test frontend/app/workspace-api.test.cjs
cd frontend
npm.cmd run build
```

## Phase 8: Multi-Taxpayer Validation

**Files:**
- Use ignored real samples under `private_samples/`
- Modify only tests and fixtures needed for sanitized proof
- Test: backend and frontend full proof set

- [ ] **Step 1: Build scenario matrix**

Validate at least:

```text
hearing aid retailer
generic retail
food service
construction
software/service business
medical/pharmacy-like business
```

- [ ] **Step 2: Include document varieties**

Use:

```text
description-rich invoice
brand/model-only invoice
mixed VAT invoice
unknown service invoice
new customer/supplier invoice
line split unavailable invoice
```

- [ ] **Step 3: Full verification**

Run:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
cd frontend
npm.cmd run build
git diff --check
```

Expected:

```text
all backend tests pass
frontend tests pass
frontend build passes
no whitespace errors
```

## Open Decisions Before Implementation

1. Should AI calls be allowed for every brand/model-only line, or only when static confidence is below 85?
2. Should global product phrase cache be editable by accountant from the first release, or should edit UI wait until after backend behavior is proven?
3. When research cache says a phrase is global but one client wants a different treatment, should client-specific override always win? Recommended: yes.
4. Should low-confidence drafts be visually marked as `Taslak - ihrac edilemez`, or use the existing review badges only?
5. Should Tavily search query include supplier title every time, or only when the product phrase is too short? Recommended: include supplier title, but sanitize private invoice data.

## Implementation Order

1. Phase 1 and Phase 2 together: AI gate plus account guardrails.
2. Phase 3 and Phase 4 together: AI-to-Tavily handoff plus research-based reposting.
3. Phase 5: mixed VAT line-level correctness.
4. Phase 6: natural-language rule builder.
5. Phase 7: portal visibility.
6. Phase 8: real multi-taxpayer validation.

Do not deploy after Phase 1 alone. Deploy after Phase 2 if backend proof is clean, or after Phase 4 if product identity research behavior is included.
