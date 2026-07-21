# AI-First Invoice Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a privacy-authorized, isolated real-invoice canary through canonical AI repair, semantic account/counterparty selection, deterministic accounting gates, and produce stage-attributed quality evidence before any broad parser repair.

**Architecture:** Extend the existing private benchmark path so the same configured provider runtime reaches both PDF canonical extraction and semantic classification. Prove the wiring with a fake provider test, then run a 10-document canary in a temporary server workspace without production database writes. Repair only a proven stage-level blocker and rerun the same canary before expanding the sample.

**Tech Stack:** Python 3, `unittest`, Fisero domain parsers/simulation, configured Groq/OpenRouter/Cerebras provider chain, PowerShell/SSH, private ignored sample files.

## Global Constraints

- Original PDF/XML files remain immutable and outside Git.
- No invoice is inserted into the production database during canary execution.
- AI output cannot rewrite canonical source-line identity; deterministic validation remains authoritative.
- Provider keys and private document contents must not appear in logs or chat output.
- No commit, push, or deploy occurs without the separate Fisero release approval transaction.

---

### Task 1: Prove canonical AI reaches the private benchmark parser

**Files:**
- Modify: `backend/app/domain/pdf_invoices.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/scripts/run_private_pipeline_benchmark.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: `parse_pdf_invoice(..., canonical_extraction_provider, canonical_extraction_policy, client_identity)` and `build_ai_runtime_from_env()`.
- Produces: keyword-only canonical provider/policy arguments on `parse_invoice_folder()` and `simulate_private_matching()`; the benchmark forwards one runtime to extraction and classification.

- [ ] **Step 1: Write a failing test**

Add a fake canonical provider and assert a folder/private simulation run marks an initially invalid PDF canonical result with `canonical_ai_used` while keeping deterministic line IDs.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.<new_test_name>`

Expected: failure because `simulate_private_matching()` cannot yet forward canonical extraction dependencies.

- [ ] **Step 3: Add minimal keyword-only pass-through**

Forward `canonical_extraction_provider`, `canonical_extraction_policy`, and `client_identity` from the benchmark runtime to `parse_invoice_folder()` and then `parse_pdf_invoice()`. Preserve existing call compatibility through default `None` values.

- [ ] **Step 4: Run focused and neighboring tests**

Run the new test plus existing canonical extraction, private benchmark summary, and private simulation tests. Expected: all pass.

### Task 2: Run isolated 10-document AI-first canary

**Files:**
- Read: `private_samples/real_pilot/firma-1/**`
- Read: `private_samples/real_pilot/firma-2/**`
- Temporary server workspace: `/tmp/fisero-ai-canary-*`

**Interfaces:**
- Consumes: real invoice PDFs, matching client chart plans/profiles, production provider environment.
- Produces: sanitized aggregate counts and per-stage status without raw document text or personal identifiers.

- [ ] **Step 1: Select the fixed canary matrix**

Use ten documents spanning purchase/sale, valid/invalid deterministic canonical extraction, single/mixed VAT, multi-line, return, known/new counterparty.

- [ ] **Step 2: Record deterministic baseline**

Capture canonical status/reasons, line count, direction, draft balance, selected account source, counterparty state, and export state.

- [ ] **Step 3: Run the configured provider chain**

Execute in the worker container against a temporary copied sample directory; do not call store/database APIs.

- [ ] **Step 4: Compare stage deltas**

Report canonical AI accepted/rejected/error, semantic AI used/retried, line coverage, final balance, account/counterparty resolution, review blockers, and provider failures.

### Task 3: Repair only the proven blocker

**Files:**
- Modify/Test: only the component identified by Task 2 evidence.

**Interfaces:**
- Consumes: one reproducible canary failure and its sanitized trace.
- Produces: one regression test and the smallest root-cause fix.

- [ ] **Step 1: Reproduce the exact failure with a focused test**
- [ ] **Step 2: Confirm the failing boundary and single root-cause hypothesis**
- [ ] **Step 3: Implement the minimum fix**
- [ ] **Step 4: Re-run the focused test and the unchanged canary matrix**

Expected: the targeted stage improves without lowering canonical validation, balance, line coverage, or export safety.

### Task 4: Expand only after canary acceptance

**Files:**
- Read: `private_samples/real_pilot/**`
- Write: ignored/private benchmark artifacts only.

**Interfaces:**
- Consumes: accepted canary pipeline.
- Produces: 220-document structural quality report plus an explicitly provisional accounting-quality comparison until a real accountant reference is approved.

- [ ] **Step 1: Run the full AI-first structural pass**
- [ ] **Step 2: Cluster provider, extraction, semantic, and deterministic-gate failures**
- [ ] **Step 3: Separate automatically provable correctness from accountant judgment**
- [ ] **Step 4: Run the stable local proof set if repository code changed**

Run: `python -m unittest discover -s backend/tests`, `node --test frontend/app/*.test.cjs`, `cd frontend && npm.cmd run build`, and `git diff --check`.

