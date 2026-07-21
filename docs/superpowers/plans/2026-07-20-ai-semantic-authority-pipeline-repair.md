# AI Semantic Authority Pipeline Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI the sole discretionary product/service and real-account authority while research supplies scoped evidence and deterministic code only constructs and protects canonical identity, arithmetic, VAT, balance, line coverage, hard legal rules, and export safety.

**Architecture:** UBL/XML remains the primary canonical source and PDF discovery/repair remains an observation-only fallback. Every unresolved canonical invoice line enters one semantic AI decision path with complete client/chart/counterparty context. Research can add sourced claims to that same decision but can never classify or overwrite it; deterministic code may report a mechanically unusable AI selection and request bounded AI correction, but may never select, substitute, downgrade to, or silently fall back to another discretionary account.

**Tech Stack:** Python domain/workflow services, structured AI provider contracts, Tavily research adapter, JSON/PostgreSQL workflow evidence, `unittest`, private canary benchmark.

## Global Constraints

- UBL/XML is the primary canonical accounting source when available.
- AI never changes source identity, canonical line IDs, monetary observations, VAT values, debit/credit amounts, or export eligibility.
- AI owns product/service meaning, activity relevance, accounting treatment, and selection of the best real chart account.
- A deterministic component must not choose or substitute a discretionary account, including `genel`, `diger`, same-family, or configured default fallbacks.
- When an AI-selected code is mechanically unusable, preserve the original AI decision in the trace and issue a bounded AI correction request with the exact validation error and current real candidates. Do not silently replace or erase it.
- Research output is evidence, not accounting truth. It cannot directly populate `product_category`, `account_treatment`, or `selected_account_code` in the final result.
- Every canonical line must have exactly one accepted semantic decision and exactly one journal allocation.
- Every stage stores immutable input/output provenance: task, prompt version, candidate set, provider/model, validated response, research evidence, retry reason, and accepted result.
- Existing unrelated dirty-worktree changes must be preserved.
- This plan authorizes local implementation and verification only. Commit, push, and deploy require the separate Fisero release approval transaction.

---

## Target Invoice Pipeline

1. **Immutable intake:** Store source identity, bytes/hash, source adapter, and document version.
2. **Canonical extraction:** Parse UBL directly; use PDF discovery/repair only for observed document fields and source-positioned lines.
3. **Mechanical document validation:** Establish parties, direction evidence, canonical IDs, totals, VAT reconciliation, and source coverage without selecting a discretionary account.
4. **Semantic context assembly:** For every canonical line assemble line evidence, document context, supplier/customer identity, client NACE/activity, relevant confirmed learning, real direction-filtered chart accounts, and real counterparty candidates.
5. **Semantic authority:** Apply a genuinely matching verified rule; otherwise call AI for exactly one decision per canonical line. A static category/confidence is supporting evidence, never a reason to skip cold-start AI account selection.
6. **Evidence escalation:** If the semantic AI asks a material unresolved question, run minimized research and return sourced claims to the same AI synthesis path. Search snippets never become a classification override.
7. **Decision validation and correction:** Check response schema, canonical-line coverage, and whether the selected real account/counterparty exists and is usable. On failure preserve the attempt and retry AI with the mechanical error; do not choose a replacement account in code.
8. **Deterministic journal construction:** Bind authoritative canonical amounts and VAT to the accepted semantic decisions and construct debit/credit lines.
9. **Hard checks and export gate:** Enforce exact totals, VAT, balance, line allocation, legal rules, authorization, revision safety, and export readiness without changing semantic account choices.
10. **Immutable decision history:** Persist every attempt and the accepted revision so research, retry, review, learning, and export remain explainable.

---

### Task 1: Lock the Semantic-Authority Contract With Regression Tests

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_research_harness.py`
- Modify: `backend/tests/test_document_processing.py` if the existing workflow fixture lives there; otherwise keep the workflow assertions in `backend/tests/test_research_harness.py`

**Interfaces:**
- Consumes: current `simulate_invoice`, `process_next_job_once`, fake AI provider, fake research provider, real `AccountSelection` candidate structures.
- Produces: failing contract tests proving AI cannot be skipped or overwritten and deterministic fallback cannot choose an account.

- [ ] **Step 1: Add the generic-line cargo regression**

  Create a purchase invoice whose canonical line is `Posta Hizmet Geliri`, supplier is `Yurtiçi Kargo Servisi A.Ş.`, and chart candidates contain both `760.03.010 DİĞER ÇEŞİTLİ GİDER` and `760.03.012 KARGO GİDERLERİ`. Configure the fake AI to select `760.03.012` and assert:

  ```python
  self.assertTrue(result.ai_classification_used)
  self.assertEqual(provider.requests[0].supplier_hint, "Yurtiçi Kargo Servisi A.Ş.")
  self.assertEqual(result.ai_suggested_account_code, "760.03.012")
  self.assertEqual(result.selected_expense_account, "760.03.012")
  self.assertFalse(result.static_fallback_account)
  ```

- [ ] **Step 2: Replace the obsolete static-cargo expectation**

  Rewrite `test_invoice_ai_gate_skips_known_kargo_line` so only a verified matching rule may skip semantic AI. Static `kargo` classification and confidence alone must not skip it:

  ```python
  self.assertTrue(result.ai_classification_used)
  self.assertNotEqual(result.ai_gate_reason, "static_confident")
  self.assertEqual(len(provider.requests), 1)
  ```

- [ ] **Step 3: Add the Muson research-poisoning regression**

  Start with canonical lines `Muson Stick Contour` and `Very Vanta Mascara`. Make initial AI return cosmetics. Make research evidence include a retailer sentence containing `hızlı kargo` while official/manufacturer claims identify cosmetics. Assert the accepted semantic result remains cosmetics unless the synthesis AI explicitly changes it with a source-backed reason:

  ```python
  self.assertEqual(result["product_category"], "kisisel_bakim_kozmetik")
  self.assertNotEqual(result["product_category"], "kargo")
  self.assertEqual(result["accepted_semantic_stage"], "research_synthesis")
  self.assertIn("hızlı kargo", result["research_evidence"][0]["raw_summary"])
  ```

- [ ] **Step 4: Add the no-deterministic-substitution regression**

  Make AI return a code absent from the supplied candidates. Assert the attempt is retained, correction is requested, and neither generic candidate is selected:

  ```python
  self.assertEqual(result.ai_attempted_account_code, "760.99.999")
  self.assertEqual(result.ai_resolution_status, "ai_correction_required")
  self.assertEqual(result.selected_expense_account, "")
  self.assertNotIn(result.selected_expense_account, {"760.03.010", "770.01"})
  self.assertEqual(result.ai_retry_reason, "selected_account_not_in_candidates")
  ```

- [ ] **Step 5: Run the focused tests and confirm they fail for the current causes**

  Run:

  ```powershell
  python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_generic_yurtici_line_uses_ai_real_kargo_account backend.tests.test_phase0_domain.Phase0DomainTests.test_invoice_ai_gate_does_not_skip_cold_start_known_category backend.tests.test_phase0_domain.Phase0DomainTests.test_invalid_ai_account_requests_ai_correction_without_static_substitution backend.tests.test_research_harness.ResearchHarnessTests.test_research_shipping_snippet_cannot_overwrite_cosmetics_decision
  ```

  Expected: failures identify the current `static_confident` skip, `select_usage_account` fallback, research `classification_override`, and missing preserved trace.

---

### Task 2: Introduce an Immutable Semantic Decision Attempt Contract

**Files:**
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_research_harness.py`

**Interfaces:**
- Produces: `SemanticDecisionAttempt`-shaped serialized evidence with `attempt_id`, `stage`, `canonical_line_ids`, `prompt_version`, provider/model, candidate codes, raw/validated response, validation errors, and acceptance state.
- Consumes: current `AiClassificationResult.ai_trace`, workflow event persistence, and existing simulation result serialization.

- [ ] **Step 1: Add failing serialization tests**

  Assert initial, research-synthesis, and correction attempts remain separately available after final result persistence:

  ```python
  self.assertEqual([item["stage"] for item in stored["semantic_attempts"]], [
      "initial_account_decision",
      "research_synthesis",
      "account_correction",
  ])
  self.assertEqual(stored["semantic_attempts"][0]["accepted"], False)
  self.assertEqual(stored["semantic_attempts"][-1]["accepted"], True)
  self.assertTrue(stored["semantic_attempts"][0]["candidate_account_codes"])
  ```

- [ ] **Step 2: Define one append-only attempt shape**

  Extend the AI trace result with these exact serialized fields:

  ```python
  {
      "attempt_id": str,
      "stage": str,
      "canonical_line_ids": list[str],
      "prompt_version": str,
      "provider": str,
      "model": str,
      "candidate_account_codes": list[str],
      "candidate_counterparty_codes": list[str],
      "validated_response": dict,
      "validation_errors": list[str],
      "accepted": bool,
      "superseded_by_attempt_id": str,
  }
  ```

  Do not persist secrets, authorization headers, complete private source documents, or provider credentials.

- [ ] **Step 3: Preserve attempts during research and result rebuilding**

  Replace selective `_preserve_ai_fields` copying with explicit append-only semantic history merging. A rebuild may append an attempt and select an accepted attempt ID; it must not discard prior attempts.

- [ ] **Step 4: Run trace and persistence tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_phase0_domain backend.tests.test_research_harness
  ```

  Expected: new attempt-history tests pass; existing sanitized AI trace tests remain green.

---

### Task 3: Make AI the Only Cold-Start Semantic Account Authority

**Files:**
- Modify: `backend/app/domain/invoice_ai_gate.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/domain/chart_accounts.py`
- Modify: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: canonical line evidence, matching verified rule/binding result, client profile, chart candidates, product classifier.
- Produces: either an accepted AI/rule semantic account decision or explicit `ai_correction_required`; never a deterministic discretionary account selection.

- [ ] **Step 1: Add rule-vs-cold-start routing tests**

  Cover exactly:

  ```text
  verified matching rule -> semantic AI may be skipped
  static category only -> semantic AI runs
  high static confidence only -> semantic AI runs
  prior unconfirmed pattern -> semantic AI runs
  AI provider failure -> no discretionary account substitution
  ```

- [ ] **Step 2: Narrow `invoice_ai_gate` to genuine resolved authority**

  Remove `static_confident` as a completed accounting decision. The gate may bypass AI only when a verified rule/binding covers the affected canonical line and all preconditions still match. Hard legal/VAT rules may constrain or block export but do not select an ordinary expense/stock/revenue detail account.

- [ ] **Step 3: Remove runtime use of deterministic discretionary selectors**

  Stop calling `_purchase_expense_account_for_line` and `_purchase_stock_account_for_line` as fallbacks after semantic routing. Keep `select_usage_account` only where it is demonstrably non-authoritative candidate ordering, or delete the unused discretionary path after call-site tests prove no consumers remain.

- [ ] **Step 4: Preserve AI choice through journal construction**

  The selected journal account must come from the accepted semantic attempt or verified rule binding:

  ```python
  purchase_account = accepted_semantic_decision.account_code
  ```

  No expression may use `guarded_ai_account or static_fallback_account`.

- [ ] **Step 5: Run focused domain tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_phase0_domain
  ```

  Expected: cargo, provider-failure, verified-rule, multi-line, mixed-VAT, and no-invented-account tests pass without a generic deterministic account fallback.

---

### Task 4: Convert Research From Classifier to Evidence Provider

**Files:**
- Modify: `backend/app/domain/research_harness.py`
- Modify: `backend/app/domain/product_research_cache.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/tests/test_research_harness.py`

**Interfaces:**
- Produces: line-scoped `research_evidence` containing the question, claims, source URL/domain/type, evidence summary, confidence, conflicts, and canonical line IDs.
- Does not produce an authoritative accounting category, treatment, or account.

- [ ] **Step 1: Add evidence-shape and poisoning tests**

  Assert each research claim is source-scoped and shipping/site-navigation phrases cannot directly set a product category:

  ```python
  self.assertEqual(profile["research_evidence"][0]["canonical_line_ids"], ["line-1"])
  self.assertIn("source_url", profile["research_evidence"][0])
  self.assertNotIn("authoritative_product_category", profile)
  self.assertNotIn("selected_account_code", profile)
  ```

- [ ] **Step 2: Remove `_infer_category_from_research` from accounting authority**

  Delete or isolate the first-keyword `classify_product_line` call so concatenated query/answer/snippets cannot create `classification_override`. Backward-compatible display labels may remain only if they are explicitly non-authoritative and never enter journal selection.

- [ ] **Step 3: Store claims and provenance, not copied verdicts**

  Normalize research into:

  ```python
  {
      "question": str,
      "canonical_line_ids": list[str],
      "claims": [{
          "claim": str,
          "source_url": str,
          "source_domain": str,
          "source_kind": "official" | "manufacturer" | "retailer" | "other",
          "evidence_summary": str,
          "confidence": int,
      }],
      "conflicts": list[str],
  }
  ```

- [ ] **Step 4: Keep privacy and cache boundaries**

  Retain sanitized minimal queries, source allow/quality policy, canonical-line scoping, cache provenance, and confidence metadata. Cache lookup must not turn an old research label into an authoritative current invoice classification.

- [ ] **Step 5: Run research tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_research_harness
  ```

  Expected: all research queries remain sanitized; evidence is source-scoped; keyword order cannot change accounting category.

---

### Task 5: Add Research Synthesis and Bounded AI Correction

**Files:**
- Modify: `backend/app/domain/ai_classification.py`
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_research_harness.py`

**Interfaces:**
- Consumes: original semantic context, prior semantic attempt, line-scoped research evidence or mechanical validation error.
- Produces: a new structured semantic attempt for the same exact canonical line IDs and real candidate set.

- [ ] **Step 1: Add synthesis and correction contract tests**

  Assert:

  ```python
  self.assertEqual(synthesis_request.stage, "research_synthesis")
  self.assertEqual(synthesis_request.canonical_line_ids, initial_request.canonical_line_ids)
  self.assertEqual(synthesis_request.account_candidates, initial_request.account_candidates)
  self.assertEqual(correction_request.validation_errors, ["selected_account_not_in_candidates"])
  ```

- [ ] **Step 2: Add short stage-specific instructions**

  `research_synthesis` instruction:

  ```text
  Canonical satır ve mevcut mükellef bağlamını esas al. Araştırma sonuçlarını yalnız kaynaklı ek kanıt olarak değerlendir. Sayfa teslimat, menü veya reklam ifadelerini ürün/hizmet kimliği sanma. Her canonical_line_id için yalnız verilen gerçek hesap adaylarından en uygun hesabı seç ve çelişen kanıtı açıkla.
  ```

  `account_correction` instruction:

  ```text
  Önceki semantik karar korunmuştur ancak seçilen hesap mekanik olarak kullanılamıyor. Verilen doğrulama hatasını ve güncel gerçek hesap adaylarını kullanarak aynı canonical_line_id için yeni hesap seç. Genel hesaba sırf kullanılabilir olduğu için geçme; ekonomik anlamı koru.
  ```

- [ ] **Step 3: Replace research rebuild with synthesis**

  Remove the `_rebuild_result_with_research(... classification_override=...)` authority path. Append research evidence, call semantic synthesis, validate it, and mark only the validated synthesis attempt accepted.

- [ ] **Step 4: Bound correction behavior**

  Permit one schema/candidate correction retry per semantic stage before provider-chain fallback. Exhaustion keeps the strongest AI proposal and exact failure visible in focused review; deterministic code still does not select another account.

- [ ] **Step 5: Run semantic and research suites**

  Run:

  ```powershell
  python -m unittest backend.tests.test_phase0_domain backend.tests.test_research_harness
  ```

  Expected: Muson remains cosmetics, Yurtiçi selects `760.03.012`, invalid codes cause bounded AI correction, and all attempts remain inspectable.

---

### Task 6: Prove Deterministic Journal Construction Never Changes Semantic Decisions

**Files:**
- Modify: `backend/app/domain/journal_entries.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Modify: `backend/app/domain/canonical_invoices.py` only if an existing canonical allocation contract needs extension
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/tests/test_normalized_invoice_journal.py`
- Modify: `backend/tests/test_normalized_invoice_journal_postgres.py`

**Interfaces:**
- Consumes: accepted semantic decision per canonical line plus canonical monetary/VAT evidence.
- Produces: balanced draft lines with exact canonical allocations and unchanged accepted account codes.

- [ ] **Step 1: Add semantic immutability assertions**

  For every draft allocation assert:

  ```python
  self.assertEqual(
      allocation["account_code"],
      accepted_by_line_id[allocation["canonical_line_id"]]["account_code"],
  )
  ```

- [ ] **Step 2: Add line coverage and balance assertions**

  Assert every canonical line occurs once, allocation totals equal canonical net/VAT values, and total debit equals total credit. Include single-line, multi-line, mixed-VAT, return, and non-deductible hard-rule cases.

- [ ] **Step 3: Separate hard-rule constraint from semantic substitution**

  A hard legal/KDV rule may add tax/review/export consequences. It must not silently rewrite the ordinary AI-selected product/service account. If a legally mandatory account treatment genuinely determines an account, record the explicit hard-rule ID and legal evidence as the decision source rather than disguising it as deterministic fallback.

- [ ] **Step 4: Run normalized persistence tests**

  Run:

  ```powershell
  python -m unittest backend.tests.test_normalized_invoice_journal backend.tests.test_normalized_invoice_journal_postgres
  ```

  Expected: accepted account codes, canonical allocations, revision fencing, and balance remain intact through persistence.

---

### Task 7: Run the Full Canary With Stage-Attributed Quality Evidence

**Files:**
- Modify: `backend/scripts/run_private_pipeline_benchmark.py`
- Modify: `backend/tests/test_private_pipeline_benchmark.py` if present; otherwise add focused script tests to the existing benchmark test module
- Update after proof only: `docs/accounting-invoice-automation-plan.md`
- Update after proof only: `docs/current-handoff.md`

**Interfaces:**
- Consumes: privacy-authorized real UBL/PDF folders, real client chart plans, configured provider chain, immutable semantic trace.
- Produces: per-document and aggregate stage-quality report without exposing private source content.

- [ ] **Step 1: Add benchmark fields and aggregation tests**

  Report at minimum:

  ```text
  canonical_line_count
  semantic_ai_called
  verified_rule_applied
  initial_account_code
  research_requested
  research_changed_decision
  accepted_account_code
  deterministic_account_substitution
  semantic_attempt_count
  line_coverage_ok
  vat_reconciled
  balanced
  export_status
  trace_complete
  ```

- [ ] **Step 2: Run targeted real regressions first**

  Run the five Yurtiçi documents and Muson document. Acceptance:

  ```text
  Yurtiçi: 5/5 accepted account = 760.03.012
  Muson: product category remains cosmetics; shipping snippet does not classify the invoice
  deterministic_account_substitution = false for every document
  trace_complete = true for every AI/research document
  ```

- [ ] **Step 3: Run all authorized firms, not only Cansu**

  Use the existing private benchmark runner against every usable `real_pilot` firm with a real chart plan. Keep UBL and PDF source types separately reported; do not combine extraction failure with semantic-account failure.

- [ ] **Step 4: Enforce quality gates**

  Required structural gates:

  ```text
  missing/duplicate/shifted canonical lines = 0
  deterministic discretionary account substitutions = 0
  research direct classification overrides = 0
  incomplete semantic traces = 0
  unbalanced journals = 0 for mechanically valid invoices
  AI-selected codes absent from candidates and silently accepted = 0
  ```

  Accountant-quality acceptance remains separate: compare the protected 35-purchase/15-sales versioned corpus against accountant-approved reference decisions before declaring Phase 2 accounting quality complete.

- [ ] **Step 5: Run the stable full proof set**

  Run:

  ```powershell
  python -m unittest discover -s backend/tests
  node --test frontend/app/*.test.cjs
  Push-Location frontend
  npm.cmd run build
  Pop-Location
  git diff --check
  ```

  Expected: all tests pass, frontend build succeeds, and `git diff --check` reports no whitespace errors.

- [ ] **Step 6: Update documentation only from proven behavior**

  Record the implemented authority order, trace contract, research evidence boundary, canary metrics, remaining accountant-reference gate, and exact continuation state. Do not mark the 50-invoice accountant-quality gate complete without its reference outcomes.

---

## Acceptance Criteria

- A cold-start invoice without a verified matching rule reaches semantic AI even when a static category is known with high confidence.
- The AI receives canonical line evidence, supplier/customer identity, client activity/NACE, relevant learning, and the real direction-filtered chart/counterparty context together.
- A valid AI-selected real account is carried unchanged into journal construction.
- Deterministic code never selects or substitutes a discretionary account.
- A mechanically invalid AI code produces a preserved failed attempt plus bounded AI correction; no generic fallback appears.
- Tavily/search snippets cannot directly set product category, treatment, account, or final journal values.
- Research evidence is source-scoped and canonical-line-scoped; research synthesis is another traceable AI attempt.
- Every canonical line has exactly one accepted semantic decision and one journal allocation.
- Exact totals, VAT, balance, hard rules, revision safety, authorization, and export eligibility remain deterministic.
- Yurtiçi and Muson regressions pass, all authorized canary firms are reported, and the stable full proof set passes.

## Verification and Release Boundary

- Local implementation must follow TDD task by task and preserve the dirty worktree.
- Do not commit incrementally under this plan because Fisero treats commit, push, and deploy as one separately approved release transaction.
- After all local verification passes, present the exact changed files, branch, remote, production target, verification evidence, and material risks; ask once for approval of `commit + push + deploy`.

