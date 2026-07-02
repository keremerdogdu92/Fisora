# Two-Stage AI Account Candidate Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed narrow AI account-candidate slice with a measured two-stage account/counterparty selection flow when candidate sets are large.

**Architecture:** Keep deterministic parsing, VAT, direction, balance, candidate-list validation, and export gates in the engine. Use AI first to select a broad relevant account-family set, then use AI again only on that narrowed real chart-account and `120/320` counterparty set. Small candidate sets continue through one AI call.

**Tech Stack:** Python domain services and pytest backend tests; existing Groq/OpenRouter/Cerebras-compatible provider adapter; existing workflow telemetry records; existing portal review debug panels.

---

## File Map

- Modify `backend/app/domain/ai_classification.py`: add stage-aware request payloads, dynamic candidate limits, and validation for family-selection output.
- Modify `backend/app/domain/matching_simulation.py`: build compact family maps, choose one-stage vs two-stage strategy, pass narrowed real account/cari candidates into final AI selection.
- Modify `backend/app/workflows/document_processing.py`: record stage telemetry in pipeline details and AI usage events.
- Modify `backend/tests/test_phase0_domain.py`: cover one-stage, two-stage, and no-invented-account behavior.
- Optionally modify `frontend/app/portal-review-panels.tsx`: show AI stage, candidate count, and selected family set in the decision details.

## Task 1: Add Candidate Strategy Model

- [ ] Add a small strategy model in `backend/app/domain/ai_classification.py`:

```python
@dataclass(frozen=True)
class AiCandidateStrategy:
    mode: str  # "single_stage" | "two_stage"
    stage: str  # "final_account" | "family_select"
    account_candidate_count: int
    counterparty_candidate_count: int
    selected_families: tuple[str, ...] = ()
```

- [ ] Default to `single_stage/final_account` when the real account candidate count is at or below the configured threshold.
- [ ] Use env defaults:

```text
FISORA_AI_SINGLE_STAGE_ACCOUNT_LIMIT=40
FISORA_AI_FINAL_STAGE_ACCOUNT_LIMIT=120
FISORA_AI_COUNTERPARTY_LIMIT=80
```

## Task 2: Build Compact Family Stage

- [ ] In `matching_simulation.py`, derive a compact family map from existing semantic candidate groups.
- [ ] The family map must include only compact data:

```json
{
  "family": "153",
  "label": "Ticari mallar / alinan cihazlar",
  "groups": ["purchase_stock"],
  "candidate_count": 18,
  "examples": ["153.01.001 ALINAN CIHAZLAR", "153.03 PIL VE AKSESUAR"]
}
```

- [ ] For purchase invoices, include relevant stock, fixed asset, expense, VAT, and supplier families. For sales invoices, include revenue, VAT, and customer families.
- [ ] Stage 1 must return multiple families, not one forced family. For device/stock/fixed-asset ambiguity, keep neighboring families such as `153`, relevant `25x`, and relevant expense families available for Stage 2.

## Task 3: Add Family Selection AI Call

- [ ] Add a `family_select` schema that allows only families from the compact family map:

```json
{
  "selected_account_families": ["153", "25"],
  "reason": "short explanation",
  "confidence": 0.0,
  "needs_research": false,
  "research_query": ""
}
```

- [ ] Validation rule: ignore any family not present in the supplied family map.
- [ ] Fallback rule: if Stage 1 fails, use deterministic broad families for the invoice direction instead of producing an empty draft.

## Task 4: Final Account and Cari Stage

- [ ] Build Stage 2 account candidates by filtering real chart-account candidates to Stage 1 families and semantic groups.
- [ ] Add the direction-specific cari set at this stage:
  - purchase: existing matched supplier plus relevant `320` candidates and new `320.<VKN/TCKN>` suggestion.
  - sales: existing matched customer plus relevant `120` candidates and new `120.<VKN/TCKN>` suggestion.
- [ ] Reuse existing final AI schema for `suggested_account_code` and `suggested_counterparty_code`, but validate against the Stage 2 candidates.
- [ ] If Stage 2 returns a valid account candidate, do not replace it with a broader deterministic fallback. Keep export gated by review and hard legal/VAT rules.

## Task 5: Telemetry and Debug Evidence

- [ ] Record these fields for every AI stage:

```json
{
  "ai_stage": "family_select",
  "candidate_strategy": "two_stage",
  "account_candidate_count": 86,
  "counterparty_candidate_count": 21,
  "input_chars": 3200,
  "selected_account_families": ["153", "25"],
  "selected_account_code": "",
  "selected_counterparty_code": "",
  "fallback_reason": ""
}
```

- [ ] Surface stage evidence in the portal decision details without making it a primary workflow control.

## Task 6: Tests

- [ ] Add `test_small_candidate_set_uses_single_stage_ai_selection`.
- [ ] Add `test_large_candidate_set_uses_family_stage_then_final_account_stage`.
- [ ] Add `test_family_stage_keeps_neighbor_families_for_device_ambiguity`.
- [ ] Add `test_final_stage_cannot_select_account_outside_narrowed_candidates`.
- [ ] Add `test_purchase_final_stage_includes_supplier_counterparty_candidates`.
- [ ] Add `test_two_stage_telemetry_records_candidate_counts_and_input_size`.

Run:

```powershell
python -m pytest backend/tests/test_phase0_domain.py -q
node --test frontend/app/product-language.test.cjs
git diff --check
```

Expected:

```text
backend test file passes
frontend text contract test passes
no whitespace errors
```

## Acceptance Criteria

- AI is no longer limited to an arbitrary first 12 account candidates.
- Small candidate sets still cost one provider call.
- Large candidate sets cost at most two provider calls for account/cari selection.
- AI cannot invent account or cari codes outside the supplied candidate lists.
- Bera/Odyoloji-like equipment invoices can see `153`, relevant `25x`, and nearby expense alternatives before choosing the final account.
- Every AI selection stage leaves enough telemetry to compare quality and provider cost.
