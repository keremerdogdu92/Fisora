# PDF Discovery and Task-aware AI Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-controlled PDF line discovery plus task-specific prompts and provider ordering without changing the UBL-first path or AI/deterministic accounting boundary.

**Architecture:** `CanonicalExtractionRequest` carries an explicit discovery/repair mode and produces a mode-specific strict schema. PDF processing binds repair results to existing IDs or assigns discovery identities from validated source positions. The worker builds separate canonical, classification, and counterparty provider chains by reordering only configured providers.

**Tech Stack:** Python dataclasses, strict JSON Schema, `Decimal`, `unittest`, existing Fisero provider adapters and canonical validators.

## Global Constraints

- UBL/XML remains the primary canonical source and its path is unchanged.
- AI never owns invoice arithmetic, canonical identity, VAT totals, balance, or export eligibility.
- Existing dirty-worktree changes are preserved.
- No commit, push, deploy, or production data mutation in this plan execution.

---

### Task 1: Mode-specific canonical extraction contract

**Files:**
- Modify: `backend/app/domain/canonical_invoices.py`
- Modify: `backend/app/domain/openai_provider.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: `CanonicalExtractionRequest(document_text, deterministic_payload, client_identity, max_input_chars, mode)`.
- Produces: `canonical_extraction_output_schema(line_ids=(), mode="repair")` and mode-specific provider instructions.

- [ ] Write a failing test proving repair keeps exact `canonical_line_id` enum/count while discovery requires blank provider identity and permits a discovered line count independent of deterministic anchors.
- [ ] Run `python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_canonical_extraction_request_separates_discovery_from_repair` and confirm the missing `mode` contract fails.
- [ ] Add the frozen `mode` field, validate `repair|discovery`, create short discovery and repair instructions, and keep monetary fields observation-only.
- [ ] Run the focused canonical prompt/schema tests and confirm they pass.

### Task 2: Server-controlled PDF discovery binding

**Files:**
- Modify: `backend/app/domain/pdf_invoices.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_normalized_invoice_journal.py`

**Interfaces:**
- Consumes: provider discovery payload with blank/untrusted IDs and source-positioned observed lines.
- Produces: `_bind_ai_discovery_payload(payload, deterministic)` with server-generated stable IDs and `_canonical_extraction_mode(deterministic)`.

- [ ] Write a failing test where the deterministic parser has one incomplete row but the provider discovers two source-positioned rows; assert two unique server IDs, deterministic total reconciliation, and `canonical_ai_discovery_used`.
- [ ] Write a failing test rejecting duplicate or empty discovery source positions and preserving the deterministic candidate.
- [ ] Run both tests and confirm they fail because discovery is currently forced through repair coverage.
- [ ] Implement discovery-mode selection for `line_items_missing`, `line_total_mismatch`, `gross_total_mismatch`, and `line_gross_total_mismatch`; retain repair for field-only validation failures.
- [ ] Clear provider IDs, reject bad source locators, generate IDs through the existing stable-ID validator, apply deterministic arithmetic, and accept only a valid candidate.
- [ ] Run the focused PDF canonical and normalized line-identity tests.

### Task 3: Stage-specific semantic prompts

**Files:**
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/ai_classification.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: `AiClassificationRequest.context.candidate_strategy.stage`.
- Produces: separate instructions for `family_select`, `line_batch`/final account selection, and `counterparty_resolve` while preserving existing output schemas.

- [ ] Write a failing test capturing provider requests for the three stages and asserting that each receives only its relevant concise task instruction.
- [ ] Run the test and confirm it fails against the shared generic prompt.
- [ ] Add stage-specific instruction selection and expose the selected prompt to existing AI trace evidence.
- [ ] Run focused provider and AI trace tests.

### Task 4: Task-aware provider chain order

**Files:**
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/workflows/document_processing.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_workflow_store.py`

**Interfaces:**
- Consumes: configured base provider membership plus optional `FISORA_AI_CANONICAL_PROVIDER_CHAIN`, `FISORA_AI_CLASSIFICATION_PROVIDER_CHAIN`, and `FISORA_AI_COUNTERPARTY_PROVIDER_CHAIN`.
- Produces: canonical `cerebras>groq>openrouter`, classification `groq>cerebras>openrouter`, and counterparty `cerebras>groq>openrouter`, limited to configured providers.

- [ ] Write failing runtime tests asserting each task chain order and verifying that a base chain containing only Groq never attempts to construct missing providers.
- [ ] Write a failing routing test proving `counterparty_resolve` uses the counterparty chain while `line_batch` uses classification.
- [ ] Run the focused tests and confirm the single shared provider chain fails them.
- [ ] Implement reusable configured-name parsing/reordering and a classification-stage routing provider that preserves last-provider/model/prompt trace metadata.
- [ ] Build the three runtime providers independently and retain the existing statement provider behavior.
- [ ] Run focused runtime, worker, capacity, and provider fallback tests.

### Task 5: Verification and documentation truth

**Files:**
- Modify: `docs/product-plan/00-canonical-decision-register.md`
- Modify: `docs/product-plan/02-system-architecture-document.md`
- Modify: `docs/accounting-invoice-automation-plan.md`

**Interfaces:**
- Consumes: verified implementation behavior.
- Produces: canonical documentation distinguishing UBL-first, PDF discovery/repair, and task-aware provider ordering.

- [ ] Run `python -m unittest discover -s backend/tests` and require zero failures.
- [ ] Run `node --test frontend/app/*.test.cjs` and require zero failures.
- [ ] Run `Push-Location frontend; npm.cmd run build; Pop-Location` and require exit code 0.
- [ ] Run `git diff --check` and require no whitespace errors.
- [ ] Update canonical documents only with behavior proven by the preceding commands; retain the 50-real-invoice accountant-quality gate as open.
- [ ] Review the final diff for unrelated or secret-bearing changes. Do not commit, push, deploy, or run production documents.
