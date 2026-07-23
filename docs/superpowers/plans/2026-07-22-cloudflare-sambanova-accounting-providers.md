# Cloudflare and SambaNova Accounting Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Cloudflare Workers AI and SambaNova as configured OpenAI-compatible accounting providers without changing deterministic accounting or export safety gates.

**Architecture:** Reuse `ChatCompletionsAccountingProvider`. Cloudflare builds its endpoint from the configured account ID and authenticates with `CLOUDFLARE_API_TOKEN`; SambaNova uses its fixed chat-completions endpoint and `SAMBANOVA_API_KEY`. Runtime, readiness, capacity, secret redaction, Docker forwarding, and ignored production configuration recognize both providers.

**Tech Stack:** Python 3, `httpx`, `unittest`, Docker Compose, environment-based secret configuration.

## Global Constraints

- Preserve the existing NVIDIA provider work and unrelated dirty-worktree changes.
- Never print or commit provider secret values.
- Cloudflare default model is `@cf/openai/gpt-oss-120b`.
- SambaNova default model is `gpt-oss-120b`.
- Cloudflare endpoint is `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions`.
- SambaNova endpoint is `https://api.sambanova.ai/v1/chat/completions`.
- Provider output remains semantic input; deterministic VAT, balance, account-family, authorization, and export gates remain authoritative.
- External smoke requests use synthetic content only.
- Do not commit, push, or deploy without separate user approval.

---

### Task 1: Add provider runtime construction

**Files:**
- Modify: `backend/app/domain/openai_provider.py`
- Modify: `backend/app/workflows/document_processing.py`
- Test: `backend/tests/test_workflow_store.py`

**Interfaces:**
- Consumes: `ChatCompletionsAccountingProvider(api_key, model, chat_completions_url, provider_name, key_name)`.
- Produces: `_accounting_provider_from_env("cloudflare", env)` and `_accounting_provider_from_env("sambanova", env)`.

- [x] Write a failing runtime test for a chain containing Cloudflare and SambaNova.
- [x] Run the targeted test and confirm failure because both names are filtered from the supported provider set.
- [x] Add endpoint/model constants and factory branches; require Cloudflare account ID before endpoint construction.
- [x] Add both names to supported provider sets and task-aware ordering without changing downstream accounting behavior.
- [x] Run provider-chain tests and confirm GREEN.

### Task 2: Add readiness, capacity, and credential redaction

**Files:**
- Modify: `backend/app/domain/production_readiness.py`
- Modify: `backend/app/domain/ai_capacity.py`
- Modify: `backend/app/domain/ai_classification.py`
- Test: `backend/tests/test_phase0_domain.py`

**Interfaces:**
- Consumes: provider names, model env variables, and key env variables.
- Produces: safe readiness/capacity projections and redacted semantic traces.

- [x] Write failing tests for configured readiness, missing Cloudflare account ID, capacity visibility, and secret redaction.
- [x] Run the targeted tests and confirm expected failures.
- [x] Map provider keys/models and treat Cloudflare account ID as required configuration.
- [x] Extend credential redaction for SambaNova and Cloudflare token values without exposing secrets.
- [x] Run the targeted tests and confirm GREEN.

### Task 3: Forward configuration to backend and worker

**Files:**
- Modify: `docker-compose.production.yml`
- Modify: `deploy/production.env.example`
- Modify: ignored `deploy/production.env`

**Interfaces:**
- Consumes: local ignored secret values.
- Produces: identical provider configuration inside backend and worker containers.

- [x] Add model, endpoint, account ID, and key variables to both Compose services.
- [x] Add empty tracked placeholders and non-secret defaults to `deploy/production.env.example`.
- [x] Preserve existing local secrets while adding the providers to the configured chain.
- [x] Render Compose configuration and verify variable presence without printing values.

### Task 4: Verify safety and synthetic provider connectivity

**Files:**
- Test: existing backend test suites.

**Interfaces:**
- Consumes: configured provider runtime.
- Produces: local regression evidence and secret-safe external connectivity evidence.

- [x] Run targeted provider/readiness/redaction tests.
- [x] Run backend unit tests, frontend tests/build, and `git diff --check`.
- [x] Inspect the diff to confirm VAT, journal balance, learning, authorization, and export code is unchanged.
- [x] Run one minimal synthetic structured request per new provider without printing payload secrets or headers.
- [x] Report provider connectivity separately from accounting correctness and real-accountant acceptance.
