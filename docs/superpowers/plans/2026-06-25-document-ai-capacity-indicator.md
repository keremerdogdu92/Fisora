# Document AI Capacity Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show continuously refreshed, conservative remaining capacity for the Belge ajanı and Araştırma ajanı on the document-processing page without triggering AI work.

**Architecture:** Keep `GET /phase0/store/ai-capacity` as the single contract. Extend its backend snapshot normalization and conservative estimate metadata, configure the existing React Query hook to refresh safely, and render a small passive status strip in `DocumentProcessingWorkspace`. The operations page continues to consume the same totals so both screens agree.

**Tech Stack:** Python 3, FastAPI, httpx, unittest, Next.js/React, TypeScript, TanStack Query, Node test runner, CSS.

---

## File map

- Modify `backend/app/domain/ai_capacity.py`: normalize Tavily usage, calculate conservative document/research capacity, and expose estimate metadata.
- Modify `backend/app/api/phase0_routes_operations.py`: refresh OpenRouter/Tavily snapshots with a ten-minute cache and preserve the latest successful snapshot on errors.
- Modify `backend/tests/test_phase0_domain.py`: unit-test conservative capacity and Tavily normalization.
- Modify `backend/tests/test_auth_policy.py`: route-level proof for Tavily usage refresh, cache reuse, auth, and secret suppression.
- Modify `frontend/app/portal-types.ts`: type the capacity metadata and nullable estimates.
- Modify `frontend/app/features/workspace/queries.ts`: enable five-minute polling and focus refresh for only the capacity query.
- Modify `frontend/app/portal-documents-view.tsx`: render the passive two-agent capacity strip.
- Modify `frontend/app/portal-app.tsx`: pass capacity data/query state into the document route.
- Modify `frontend/app/styles.css`: add subtle responsive capacity-strip styling.
- Modify `frontend/app/product-language.test.cjs`: protect labels and passive copy.
- Modify `frontend/app/portal-routes.test.cjs`: verify the document route receives capacity state without embedding implementation in the shell.

### Task 1: Conservative capacity domain model

**Files:**
- Modify: `backend/tests/test_phase0_domain.py`
- Modify: `backend/app/domain/ai_capacity.py`

- [ ] **Step 1: Write failing domain tests**

Add tests that define the conservative contract:

```python
def test_ai_capacity_reserves_retry_budget_for_documents(self) -> None:
    payload = ai_capacity_payload(
        env={
            "FISORA_AI_PROVIDER_CHAIN": "groq",
            "GROQ_API_KEY": "gsk-secret",
            "FISORA_AI_MAX_PROVIDER_CALLS": "3",
            "FISORA_AI_STATEMENT_MAX_PROVIDER_CALLS": "3",
        },
        provider_snapshots={
            "groq": normalize_groq_rate_limit_headers(
                {"x-ratelimit-remaining-requests": "742"}
            )
        },
    )

    self.assertEqual(payload["totals"]["document_queries"], 92)
    self.assertEqual(payload["estimate"]["estimate_mode"], "conservative")
    self.assertEqual(payload["estimate"]["reserve_percent"], 25)
    self.assertEqual(payload["estimate"]["retry_multiplier"], 2)


def test_tavily_usage_normalization_and_conservative_research_capacity(self) -> None:
    snapshot = normalize_tavily_usage_payload(
        {
            "key": {"usage": 150, "limit": 1000},
            "account": {"plan_usage": 500, "plan_limit": 15000},
        }
    )
    payload = ai_capacity_payload(
        env={
            "FISORA_RESEARCH_ENABLED": "true",
            "FISORA_RESEARCH_PROVIDER": "tavily",
            "TAVILY_API_KEY": "tvly-secret",
        },
        provider_snapshots={"tavily": snapshot},
    )

    self.assertEqual(snapshot["credit"]["remaining"], 850)
    self.assertEqual(payload["totals"]["internet_researches"], 318)
    self.assertEqual(payload["estimate"]["confidence"], "live")


def test_research_capacity_is_unknown_without_a_usage_snapshot(self) -> None:
    payload = ai_capacity_payload(
        env={
            "FISORA_RESEARCH_ENABLED": "true",
            "FISORA_RESEARCH_PROVIDER": "tavily",
            "TAVILY_API_KEY": "tvly-secret",
        },
        provider_snapshots={},
    )

    research = next(agent for agent in payload["agents"] if agent["kind"] == "research")
    self.assertIsNone(research["estimates"]["internet_researches"])
    self.assertIsNone(payload["totals"]["internet_researches"])
    self.assertEqual(payload["estimate"]["confidence"], "not_available")
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_ai_capacity_reserves_retry_budget_for_documents backend.tests.test_phase0_domain.Phase0DomainTests.test_tavily_usage_normalization_and_conservative_research_capacity backend.tests.test_phase0_domain.Phase0DomainTests.test_research_capacity_is_unknown_without_a_usage_snapshot
```

Expected: FAIL because `normalize_tavily_usage_payload` and the `estimate` contract do not exist and current estimates are optimistic.

- [ ] **Step 3: Implement Tavily normalization and conservative helpers**

In `backend/app/domain/ai_capacity.py`, add:

```python
CAPACITY_RESERVE_PERCENT = 25
CAPACITY_RETRY_MULTIPLIER = 2
TAVILY_CREDITS_PER_RESEARCH = 2


def normalize_tavily_usage_payload(payload: Mapping[str, object]) -> dict[str, object]:
    key = payload.get("key") if isinstance(payload.get("key"), Mapping) else {}
    limit = _int_or_none(key.get("limit"))
    usage = _int_or_none(key.get("usage"))
    remaining = max(limit - usage, 0) if limit is not None and usage is not None else None
    return {
        "source": "usage_endpoint",
        "credit": {"limit": limit, "used": usage, "remaining": remaining, "reset": ""},
        "last_checked_at": utc_now(),
    }


def _safe_capacity(remaining: int | None, *, units_per_item: int) -> int | None:
    if remaining is None:
        return None
    reserved = remaining * (100 - CAPACITY_RESERVE_PERCENT)
    return max(reserved // 100 // max(units_per_item, 1), 0)
```

Change document capacity to use:

```python
return _safe_capacity(
    remaining,
    units_per_item=max(requests_per_document, 1) * CAPACITY_RETRY_MULTIPLIER,
)
```

Pass the Tavily snapshot into `_research_agent`, calculate:

```python
internet_researches = _safe_capacity(
    remaining_credit,
    units_per_item=TAVILY_CREDITS_PER_RESEARCH,
)
```

Use `None`, not `0`, when a configured provider has no measurable snapshot. Add:

```python
"estimate": {
    "estimate_mode": "conservative",
    "confidence": confidence,
    "last_checked_at": latest_checked_at,
    "reserve_percent": CAPACITY_RESERVE_PERCENT,
    "retry_multiplier": CAPACITY_RETRY_MULTIPLIER,
}
```

Compute totals only from measurable agents; return `None` when no agent of that kind is measurable.

- [ ] **Step 4: Run domain tests and verify GREEN**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain
```

Expected: all domain tests PASS. Update older assertions that expected optimistic `>= 247` or configured-only research values so they assert the new conservative/unknown semantics.

- [ ] **Step 5: Commit the domain change**

```powershell
git add backend/app/domain/ai_capacity.py backend/tests/test_phase0_domain.py
git commit -m "Make AI capacity estimates conservative"
```

### Task 2: Cached Tavily usage snapshot

**Files:**
- Modify: `backend/tests/test_auth_policy.py`
- Modify: `backend/app/api/phase0_routes_operations.py`

- [ ] **Step 1: Write failing route tests**

Patch `httpx.get` and add a Tavily-backed route test that:

```python
usage_response.json.return_value = {
    "key": {"usage": 150, "limit": 1000},
    "account": {"plan_usage": 500, "plan_limit": 15000},
}
```

Assert:

```python
self.assertEqual(response.status_code, 200)
self.assertEqual(response.json()["totals"]["internet_researches"], 318)
http_get.assert_called_once_with(
    "https://api.tavily.com/usage",
    headers={"Authorization": "Bearer tvly-secret"},
    timeout=2.0,
)
self.assertNotIn("tvly-secret", str(response.json()))
```

Issue a second request against the same temporary store and assert the external usage endpoint is not called again while the snapshot is under ten minutes old.

Add a failure case where the usage endpoint raises `httpx.ConnectError`; seed the store with a previous Tavily snapshot and assert the endpoint returns that last known estimate with `estimate.confidence == "cached"`.

- [ ] **Step 2: Run the route tests and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy.AuthPolicyTests.test_ai_capacity_endpoint_requires_accountant_and_hides_secrets
```

Expected: FAIL because Tavily usage is not requested or cached.

- [ ] **Step 3: Implement generic snapshot freshness and Tavily refresh**

In `backend/app/api/phase0_routes_operations.py`, add:

```python
from datetime import UTC, datetime, timedelta
from app.domain.ai_capacity import (
    ai_capacity_payload,
    normalize_openrouter_key_payload,
    normalize_tavily_usage_payload,
)

TAVILY_USAGE_URL = "https://api.tavily.com/usage"
CAPACITY_SNAPSHOT_TTL = timedelta(minutes=10)
```

Add a freshness helper that parses `last_checked_at` and returns true only inside the TTL. Replace unconditional OpenRouter refresh with a provider-aware helper that:

1. Returns a fresh stored snapshot without network access.
2. Calls the provider usage endpoint when stale or absent.
3. Records only successful normalized responses.
4. Returns the prior snapshot on 401, 403, 429, timeout, or network failure.

For Tavily:

```python
response = httpx.get(
    TAVILY_USAGE_URL,
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=2.0,
)
```

Set a non-secret status marker on stale fallback so `ai_capacity_payload` can report `cached`.

- [ ] **Step 4: Run route tests and verify GREEN**

Run:

```powershell
python -m unittest backend.tests.test_auth_policy
```

Expected: all auth/route tests PASS and no response contains provider keys.

- [ ] **Step 5: Commit snapshot refresh**

```powershell
git add backend/app/api/phase0_routes_operations.py backend/tests/test_auth_policy.py
git commit -m "Track cached Tavily capacity usage"
```

### Task 3: Frontend query contract and passive indicator

**Files:**
- Modify: `frontend/app/product-language.test.cjs`
- Modify: `frontend/app/portal-routes.test.cjs`
- Modify: `frontend/app/portal-types.ts`
- Modify: `frontend/app/features/workspace/queries.ts`
- Modify: `frontend/app/portal-documents-view.tsx`
- Modify: `frontend/app/portal-app.tsx`

- [ ] **Step 1: Write failing source-contract tests**

In `frontend/app/product-language.test.cjs`, add:

```javascript
test("document processing shows passive AI agent capacity labels", () => {
  const sourceText = source("portal-documents-view.tsx");

  assert.match(sourceText, /AI kapasitesi/);
  assert.match(sourceText, /Belge ajanı/);
  assert.match(sourceText, /Araştırma ajanı/);
  assert.match(sourceText, /yaklaşık/i);
  assert.doesNotMatch(sourceText, /onClick|research\/refresh|yenile/i);
});
```

In `frontend/app/portal-routes.test.cjs`, assert `portal-app.tsx` passes `aiCapacity`, `isPending`, and `isError` into `DocumentProcessingWorkspace`.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
node --test frontend/app/product-language.test.cjs frontend/app/portal-routes.test.cjs
```

Expected: FAIL because the document view has no capacity UI or props.

- [ ] **Step 3: Extend frontend capacity types**

In `frontend/app/portal-types.ts`, make totals nullable and add:

```typescript
export type AiCapacityEstimateView = {
  estimate_mode?: "conservative" | string;
  confidence?: "live" | "cached" | "partial" | "not_available" | string;
  last_checked_at?: string;
  reserve_percent?: number;
  retry_multiplier?: number;
};
```

In the existing `AiCapacityAgentView`, replace its `estimates` field with:

```typescript
estimates?: {
  document_queries?: number | null;
  internet_researches?: number | null;
  confidence?: string;
};
```

Replace the existing `AiCapacityView` declaration with:

```typescript
export type AiCapacityView = {
  generated_at?: string;
  status?: string;
  agents?: AiCapacityAgentView[];
  totals?: {
    document_queries?: number | null;
    internet_researches?: number | null;
  };
  estimate?: AiCapacityEstimateView;
};
```

- [ ] **Step 4: Configure capacity-only refresh behavior**

In `useAiCapacityQuery`, add:

```typescript
refetchInterval: 5 * 60 * 1000,
refetchIntervalInBackground: false,
refetchOnWindowFocus: true,
placeholderData: (previousData) => previousData,
```

Do not change global query defaults or other workspace queries.

- [ ] **Step 5: Render the passive status strip**

Change `DocumentProcessingWorkspace` props to accept:

```typescript
aiCapacity?: AiCapacityView;
capacityPending: boolean;
capacityError: boolean;
```

Add a pure formatter:

```typescript
function capacityValue(
  value: number | null | undefined,
  pending: boolean,
  hasCachedValue: boolean,
) {
  if (typeof value === "number") return `≈ ${value}`;
  if (pending && !hasCachedValue) return "hesaplanıyor";
  return "ölçülemiyor";
}
```

Render:

```tsx
<div className="document-capacity-strip" aria-label="AI kapasitesi">
  <span className="document-capacity-title">AI kapasitesi</span>
  <span><strong>Belge ajanı</strong> {documentText}</span>
  <span><strong>Araştırma ajanı</strong> {researchText}</span>
  {aiCapacity?.estimate?.confidence === "cached" || capacityError ? (
    <small>son bilinen yaklaşık değer</small>
  ) : (
    <small>güvenli yaklaşık değer</small>
  )}
</div>
```

The component must contain no buttons, click handlers, links, or POST calls.

In `frontend/app/portal-app.tsx`, pass:

```tsx
aiCapacity={aiCapacityQuery.data}
capacityPending={aiCapacityQuery.isPending}
capacityError={aiCapacityQuery.isError}
```

- [ ] **Step 6: Run frontend tests and verify GREEN**

Run:

```powershell
node --test frontend/app/product-language.test.cjs frontend/app/portal-routes.test.cjs frontend/app/workspace-api.test.cjs
```

Expected: all tests PASS.

- [ ] **Step 7: Commit frontend behavior**

```powershell
git add frontend/app/product-language.test.cjs frontend/app/portal-routes.test.cjs frontend/app/portal-types.ts frontend/app/features/workspace/queries.ts frontend/app/portal-documents-view.tsx frontend/app/portal-app.tsx
git commit -m "Show AI capacity on document processing"
```

### Task 4: Subtle responsive styling

**Files:**
- Modify: `frontend/app/styles.css`

- [ ] **Step 1: Add responsive low-emphasis styles**

Add:

```css
.document-capacity-strip {
  align-items: center;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  font-size: 0.78rem;
  gap: 6px 12px;
  justify-content: flex-end;
  min-height: 24px;
}

.document-capacity-strip span:not(:first-child) {
  border-left: 1px solid var(--border);
  padding-left: 12px;
}

.document-capacity-strip strong {
  color: var(--text);
  font-weight: 600;
}

.document-capacity-strip small {
  color: var(--muted);
}

@media (max-width: 720px) {
  .document-capacity-strip {
    align-items: flex-start;
    display: grid;
    justify-content: stretch;
  }

  .document-capacity-strip span:not(:first-child) {
    border-left: 0;
    padding-left: 0;
  }
}
```

- [ ] **Step 2: Run build and source tests**

Run:

```powershell
node --test frontend/app/product-language.test.cjs frontend/app/portal-routes.test.cjs
Set-Location frontend
npm.cmd run build
Set-Location ..
```

Expected: tests PASS and Next.js build succeeds.

- [ ] **Step 3: Commit styles**

```powershell
git add frontend/app/styles.css
git commit -m "Style document capacity indicator"
```

### Task 5: Full verification

**Files:**
- Verify only; no planned source changes.

- [ ] **Step 1: Run focused backend verification**

```powershell
python -m unittest backend.tests.test_phase0_domain backend.tests.test_auth_policy
```

Expected: PASS.

- [ ] **Step 2: Run the stable backend suite**

```powershell
python -m unittest discover -s backend/tests
```

Expected: PASS.

- [ ] **Step 3: Run the stable frontend suite**

```powershell
node --test frontend/app/*.test.cjs
```

Expected: PASS.

- [ ] **Step 4: Build the frontend**

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
```

Expected: production build succeeds.

- [ ] **Step 5: Check patch integrity**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional changes remain. Existing untracked `docs/superpowers/plans/2026-06-23-portal-ui-turkish-encoding-redesign.md` and `docs/ui/` remain untouched.

- [ ] **Step 6: Browser verification**

Open `/portal/belgeler` with an accountant session and verify:

1. The capacity strip appears above the document workspace.
2. “Belge ajanı” and “Araştırma ajanı” are both visible.
3. The strip is visually secondary to the document controls.
4. No button, link, or pointer cursor suggests an action.
5. Refreshing or focusing the page updates capacity without starting document/research work.
6. Narrow viewport stacks the values without horizontal overflow.
7. Browser console has no errors.

- [ ] **Step 7: Commit any verification-only correction**

If verification required a correction, repeat its failing test first, apply the minimal fix, rerun the affected suite, then commit only those files. If no correction was needed, do not create an empty commit.
