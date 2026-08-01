# Utility Learning Rule Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route utility-provider knowledge through Fisero's existing learning-event, rule-candidate, validation, active-rule, and export-gate lifecycle.

**Architecture:** ProviderDirectory contributes `service_profile` evidence to a document and its learning event; it never contributes a global account. Accountant notes are interpreted by the existing rule-preview flow. A saved candidate is validated on the next genuinely matching document, then becomes a versioned active client rule. Active rules may bypass AI only under existing complete-coverage, current-chart, VAT, direction, counterparty, and balance gates.

**Tech Stack:** Python 3 `unittest`, existing ReviewService/LearningRuleRepository/verified_rule_authority, React/TypeScript portal review UI.

## Global Constraints

- UBL is processed alone when present; PDF is the alternative source path.
- PDF exact provider title may establish `service_profile`; it is recorded as title evidence.
- No global account code and no invented account code; a new counterparty may still be suggested through existing flow.
- Ordinary approval creates learning evidence, never an active rule.
- Active automation requires explicit accountant rule confirmation plus the next matching-document validation.
- Device/installment scope is narrow: tenant + provider + profile + normalized marker pattern + direction.
- Preserve existing versioning, tenant isolation, approved-journal immutability, and export gates.

---

### Task 1: Carry utility context into existing learning/rule payloads

**Files:**
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/domain/learning_intelligence.py`
- Modify: `backend/app/domain/review_rule_interpretation.py`
- Test: `backend/tests/test_phase0_services.py`

**Produces:** `utility_context` in learning events and rule-preview requests: provider ID/title, match kind, profile, source, marker pattern, direction.

- [ ] Write failing tests: Vodafone UBL note produces `service_profile=gsm_communication`, `provider_match_kind=vkn`; Vodafone PDF note produces `provider_match_kind=title`; ordinary invoice has no utility context.
- [ ] Run `python -m unittest backend.tests.test_phase0_services` and confirm fields are absent.
- [ ] Build context only from stored document result; do not re-parse source or infer a missing account.
- [ ] Add context to `natural_language_rule_candidate` and rule-preview document payload.
- [ ] Re-run focused tests; then `python -m unittest backend.tests.test_document_upload_api`.

### Task 2: Create utility rule candidates through existing note flow

**Files:**
- Modify: `backend/app/domain/natural_language_rule_builder.py`
- Modify: `backend/app/domain/review_rule_interpretation.py`
- Modify: `backend/app/domain/verified_rule_authority.py`
- Test: `backend/tests/test_phase0_domain.py`
- Test: `backend/tests/test_learning_rule_lifecycle.py`

**Produces:** existing candidate/rule snapshots with scope `client_service_profile` or narrow `client_utility_marker`; final account binding comes from accountant-approved draft and current tenant chart.

- [ ] Write failing tests for note `Bu mükellefe kesilen Vodafone faturaları haberleşme gideridir.`: candidate trigger is Vodafone + GSM + purchase, and no account code is required in note.
- [ ] Write failing tests for `Vodafone modem taksitleri ... haberleşme gideridir.`: candidate includes only normalized modem/taksit marker pattern.
- [ ] Implement utility-aware candidate scope selection. Default is `client_service_profile`; marker evidence creates `client_utility_marker`; an explicit provider phrase narrows the trigger, not a new global rule type.
- [ ] Rule snapshot stores semantic meaning, selected real account, provider/profile evidence, marker pattern, source review decision, actor, and version.
- [ ] Existing active-rule compiler validates account remains active/detail/direction-fit in tenant chart; marker rule outranks provider/profile rule.
- [ ] Run focused lifecycle/domain tests.

### Task 3: Wire candidate save, validation, activation, and fingerprints

**Files:**
- Modify: `backend/app/services/review_service.py`
- Modify: `backend/app/persistence/learning_rule_repository.py`
- Modify: `backend/app/workflows/document_processing.py`
- Modify: current processing fingerprint builder/repository call site
- Test: `backend/tests/test_learning_rule_lifecycle.py`
- Test: `backend/tests/test_document_upload_api.py`

**Produces:** `awaiting_first_validation` candidate after `Kural olarak kaydet`; next matching approval activates it; active rule ID/version and ProviderDirectory version enter fingerprint.

- [ ] Write failing tests: `Benzerlerde öner` persists only learning evidence; `Kural olarak kaydet` persists candidate but does not activate it.
- [ ] Write failing tests: source document never validates itself; next matching unchanged approval activates candidate; account/direction/counterparty/scope change revises candidate and resets validation.
- [ ] Write failing test: changing provider-directory version, active rule version, chart version, or prompt version changes fingerprint.
- [ ] Reuse repository version/transition API; never silently promote an event to active.
- [ ] On active rule, preserve existing complete-line/VAT/balance/counterparty/export checks. Failed precondition returns to AI draft for affected decision, not generic fallback.
- [ ] Run focused tests and `python -m unittest backend.tests.test_workflow_store`.

### Task 4: Make device/installment validation one clear extra review

**Files:**
- Modify: `backend/app/domain/utility_invoice_markers.py`
- Modify: `backend/app/domain/matching_simulation.py`
- Test: `backend/tests/test_utility_invoice_markers.py`
- Test: `backend/tests/test_phase0_domain.py`

**Produces:** first marker document requires focused review; candidate rule applies to next same marker and its unchanged approval activates rule; afterward identical matching documents bypass AI/review only when all gates pass.

- [ ] Write failing end-to-end marker tests for ordinary GSM unaffected, first modem/taksit review, next validation, active repeat, and different marker remaining in review.
- [ ] Ensure exact pattern is derived from canonical UBL line descriptions only; PDF adds no device/installment marker logic.
- [ ] Remove marker review reason only when matching active marker rule completely covers canonical lines.
- [ ] Run focused tests.

### Task 5: Add minimum accountant-facing utility rule context

**Files:**
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/portal-data-mappers.ts`
- Modify: `frontend/app/portal-review-panels.tsx`
- Modify: `frontend/app/portal-agents-view.tsx`
- Test: `frontend/app/portal-preview.test.cjs`
- Test: `frontend/app/workspace-api.test.cjs`

**Produces:** existing rule preview/card displays `Vodafone · GSM`, VKN/title evidence, `yalnız bu mükellef`, candidate/validation/active state, and marker three-step status.

- [ ] Write failing mapper/UI tests for profile evidence and marker state labels.
- [ ] Keep primary action `Onayla ve geç`; no separate training screen or account-code input.
- [ ] In candidate modal show compact trigger summary and source line for marker cases.
- [ ] On validation document show one keyboard-accessible action: `Doğrula ve kuralı etkinleştir`.
- [ ] In agents view show source document/profile/stage; link back to document instead of editing account in the card.
- [ ] Run focused Node tests.

### Task 6: Verify and update decision records

**Files:**
- Modify: `docs/product-plan/00-canonical-decision-register.md`
- Modify: `docs/accounting-invoice-automation-plan.md`
- Test: backend/frontend suites

- [ ] Run `python -m unittest discover -s backend/tests`.
- [ ] Run `node --test frontend/app/*.test.cjs`.
- [ ] Run `Push-Location frontend; npm.cmd run build; Pop-Location`.
- [ ] Run `git diff --check` and inspect changed/untracked scope.
- [ ] Record: utility title evidence, candidate-vs-active lifecycle, marker validation, fingerprint inputs, and no-invented-account rule.
- [ ] Do not commit, push, deploy, or mutate pilot corpus without release approval.
