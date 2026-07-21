# AI Observation and Deterministic Invoice Math Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make invoice AI return only source-backed observations and semantic accounting decisions while deterministic code exclusively owns VAT, totals, reconciliation, debit/credit, and journal balance.

**Architecture:** PDF AI extraction returns observed document fields with stable line IDs and evidence; it never derives or reconciles money. A deterministic assembler binds observations to trusted source lines, computes authoritative line tax/gross, VAT summary, totals, and mismatch flags. Accounting `line_batch` remains semantic and never returns monetary or debit/credit values.

**Tech Stack:** Python dataclasses, strict JSON Schema, `Decimal`, `unittest`, existing Fisero canonical invoice and matching simulation modules.

## Global Constraints

- Preserve immutable source bytes, deterministic source positions, and stable canonical line IDs.
- XML/UBL remains the preferred canonical source; this change targets AI-assisted PDF extraction.
- AI may read a printed amount but must not calculate, reconcile, fill, or alter a monetary value.
- Deterministic code owns exact totals, VAT arithmetic, debit/credit balance, line coverage, and export eligibility.
- Preserve the user's unrelated dirty-worktree changes; do not commit, push, or deploy.

---

### Task 1: Observation-only provider contract

**Files:**
- Modify: `backend/app/domain/canonical_invoices.py`
- Modify: `backend/app/domain/openai_provider.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Produces: `canonical_extraction_output_schema()` whose monetary fields are explicitly observed values.
- Produces: `CanonicalExtractionRequest.to_schema_payload()` instructions that prohibit calculations.

- [x] Write failing tests asserting the prompt contains `hesaplama`, prohibits filling missing values, contains no arithmetic equations, and the strict schema uses `observed_*` monetary fields.
- [x] Run the focused tests and confirm they fail because the current prompt asks the model to reconcile equations.
- [x] Rename AI response monetary fields to `observed_*`, keep every strict-schema property required, and replace math instructions with source-observation instructions.
- [x] Run the focused tests and confirm they pass.

### Task 2: Deterministic authoritative arithmetic

**Files:**
- Modify: `backend/app/domain/canonical_invoices.py`
- Modify: `backend/app/domain/pdf_invoices.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: observed AI fields bound to deterministic `canonical_line_id` and `source_position`.
- Produces: a canonical invoice whose `tax_amount`, `gross_amount`, VAT summary, and totals are generated only by deterministic `Decimal` arithmetic.

- [x] Write a failing test where AI reports deliberately wrong observed tax, gross, VAT summary, and totals.
- [x] Assert the completed canonical invoice uses `taxable_amount * vat_rate / 100`, not any observed derived value, and records explicit observed-value mismatch notes.
- [x] Run the test and confirm it fails against the current AI-authoritative candidate path.
- [x] Map observation fields into a non-authoritative candidate, bind trusted line identity, and always run deterministic arithmetic before accepting AI-assisted canonical data.
- [x] Keep printed totals only as comparison evidence; reject or mark review when the deterministic total conflicts beyond tolerance.
- [x] Run positive, mismatch, dropped-line, duplicate-line, and source-identity tests.

### Task 3: Semantic accounting AI boundary

**Files:**
- Modify only if required: `backend/app/domain/ai_classification.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Produces: `line_batch` decisions containing identity, meaning, account/counterparty intent, confidence, reason, research, and risk only.

- [x] Write a contract test that recursively rejects monetary, VAT, debit, credit, and balance properties from `line_batch` output schema.
- [x] Run the test; it was already green, confirming the semantic AI boundary required no production change.
- [x] Run the grouped multi-line journal test to prove deterministic code constructs a balanced journal from semantic account decisions.

### Task 4: Verification and canary gate

**Files:**
- Modify if metric coverage is missing: `backend/scripts/run_private_pipeline_benchmark.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Produces: evidence that no AI-derived monetary value becomes authoritative and every accepted line is covered once.

- [x] Run focused canonical/provider/matching tests.
- [x] Run `python -m unittest discover -s backend/tests`.
- [x] Run `node --test frontend/app/*.test.cjs`.
- [x] Run `npm.cmd run build` from `frontend`.
- [x] Run `git diff --check`.
- [x] Attempt the isolated 4-invoice canary; stop its isolated container after six minutes of provider timeout with no result, and do not run 10 or 220 invoices.

## Acceptance Criteria

- AI prompts contain no arithmetic or reconciliation request.
- AI response schema labels all document money as observed, never authoritative.
- Accepted canonical `tax_amount`, `gross_amount`, VAT summary, and totals have deterministic provenance.
- Printed/observed conflicts remain visible and cannot be silently normalized away.
- Every canonical line appears exactly once in semantic AI decisions and journal allocation.
- Provider failure cannot change deterministic invoice mathematics or export safety.
