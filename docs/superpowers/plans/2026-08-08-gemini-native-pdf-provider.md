# Gemini Native-PDF Accounting Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini 2.5 Flash-Lite as the first accounting provider for every AI task and send original PDFs through Gemini native inline-PDF structured extraction.

**Architecture:** A dedicated `GeminiAccountingProvider` implements Gemini native `generateContent`, while preserving the existing accounting-provider method contract. `CanonicalExtractionRequest` transports non-serialized PDF bytes only to adapters that support them; existing fallback adapters continue using extracted text.

**Tech Stack:** Python 3, dataclasses, httpx, unittest, Docker Compose, Gemini GenerateContent REST API.

## Global Constraints

- Never print, commit, or place `GEMINI_API_KEY` in tracked files.
- Default model is exactly `gemini-2.5-flash-lite`.
- Native PDF input uses `application/pdf` inline base64 and is capped at exactly 50,000,000 bytes.
- Gemini is first for canonical extraction, classification/account choice, counterparty resolution, and statement suggestions.
- Deterministic canonical identity, VAT, balance, authorization, accountant override, and export gates remain unchanged.
- Commit, push, secret installation, and deploy are outside local implementation authority.

---

### Task 1: Gemini native provider contract

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/canonical_invoices.py`

**Interfaces:**
- Consumes: `CanonicalExtractionRequest.to_schema_payload()` and existing accounting-provider methods.
- Produces: `GeminiAccountingProvider` with `classify_product`, `extract_invoice_canonical`, `suggest_statement_line`, and `interpret_review_rule`.

- [ ] Write a failing test that constructs a `CanonicalExtractionRequest` with PDF bytes and asserts Gemini posts `inline_data.mime_type=application/pdf`, base64 data, `responseMimeType=application/json`, the canonical `responseJsonSchema`, `x-goog-api-key`, and the default model endpoint.
- [ ] Run `python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_gemini_provider_posts_native_pdf_structured_payload` and confirm failure because `GeminiAccountingProvider` does not exist.
- [ ] Add non-repr `document_bytes` and `document_mime_type` fields to `CanonicalExtractionRequest`; keep them out of `to_schema_payload()`.
- [ ] Implement `GeminiAccountingProvider` and `_extract_gemini_json_response`; use native text-only parts for non-PDF methods and inline PDF only for canonical extraction.
- [ ] Add and RED-GREEN verify an oversize-PDF test expecting a safe `ValueError` before HTTP is called.
- [ ] Run the two Gemini provider tests and confirm PASS.

### Task 2: PDF bytes and provider routing

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/app/domain/pdf_invoices.py`
- Modify: `backend/app/workflows/document_processing.py`

**Interfaces:**
- Consumes: `GeminiAccountingProvider` and `CanonicalExtractionRequest.document_bytes`.
- Produces: provider factory support and Gemini-first task chains.

- [ ] Write a failing parser test whose fake canonical provider asserts the original `%PDF` bytes are present in the canonical request.
- [ ] Run the test and confirm failure because the parser only passes extracted text.
- [ ] Read the PDF once for canonical AI and pass bytes/MIME type through `_maybe_complete_canonical_with_ai` without changing deterministic binding or reconciliation.
- [ ] Write a failing runtime test for `gemini` factory construction and Gemini-first ordering in all task chains.
- [ ] Add Gemini constants, factory configuration, supported-provider membership, and preferred ordering.
- [ ] Run the targeted parser/runtime tests and confirm PASS.

### Task 3: Readiness, capacity, redaction, and Compose

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/app/domain/production_readiness.py`
- Modify: `backend/app/domain/ai_capacity.py`
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `docker-compose.production.yml`
- Modify: `deploy/production.env.example`

**Interfaces:**
- Consumes: `GEMINI_API_KEY` and `FISORA_GEMINI_*` values.
- Produces: secret-safe runtime/readiness/capacity configuration for backend and worker.

- [ ] Write failing tests proving Gemini readiness/capacity mapping and `AIza...` redaction.
- [ ] Run the targeted tests and confirm expected missing-provider failures.
- [ ] Add Gemini key/model mappings, supported sets, key-presence output, and redaction pattern.
- [ ] Forward all Gemini configuration variables to backend and worker; place only empty/default values in the example env.
- [ ] Run targeted readiness/capacity/redaction tests and confirm PASS.
- [ ] Run Docker Compose config validation and confirm both services receive the variable names without printing secret values.

### Task 4: Canonical policy and local verification

**Files:**
- Modify: `docs/product-plan/00-canonical-decision-register.md`
- Verify: all changed files

**Interfaces:**
- Consumes: the user-approved unpaid-Gemini active-use decision.
- Produces: canonical policy aligned with runtime behavior.

- [ ] Replace the old benchmark-only/billing-required language with the exact active-use, data-terms acceptance, deterministic-gate, and FreeLLM discovery boundaries from the design.
- [ ] Run targeted Gemini/provider/canonical tests.
- [ ] Run `python -m unittest discover -s backend/tests`.
- [ ] Run `node --test frontend/app/*.test.cjs`.
- [ ] Run `Push-Location frontend; npm.cmd run build; Pop-Location`.
- [ ] Run `git diff --check` and inspect the scoped diff without modifying unrelated dirty-worktree changes.

### Task 5: Secret-safe Gemini smoke

**Files:**
- Create: `backend/scripts/smoke_gemini_native_pdf.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: `GEMINI_API_KEY` from process environment or ignored `deploy/production.env` loading performed by the operator.
- Produces: secret-safe one-shot native-PDF smoke output containing only provider, model, elapsed time, and schema-validity status.

- [ ] Write a failing script-contract test proving missing-key output is safe and no environment value is echoed.
- [ ] Implement a small in-memory synthetic invoice PDF generator and a one-shot call through `GeminiAccountingProvider`.
- [ ] Run the contract test and confirm PASS.
- [ ] If `GEMINI_API_KEY` is present, run the smoke once; otherwise report `BLOCKED_MISSING_GEMINI_API_KEY` without claiming an API result.
- [ ] Do not call Gemini with a real PDF until the synthetic smoke returns schema-valid JSON.
