# NVIDIA Primary AI Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NVIDIA API Catalog as Fisero's primary accounting AI provider with Groq, OpenRouter, and Cerebras preserved as ordered fallbacks.

**Architecture:** Reuse the existing `ChatCompletionsAccountingProvider` because NVIDIA exposes an OpenAI-compatible chat-completions endpoint. Add NVIDIA to the provider factory, supported-provider sets, readiness/capacity projections, secret redaction, Docker environment forwarding, and ignored production configuration without changing deterministic accounting or export gates.

**Tech Stack:** Python 3, `unittest`, FastAPI domain services, `httpx`, Docker Compose, dotenv-style production configuration.

## Global Constraints

- Provider order is exactly `nvidia,groq,openrouter,cerebras`.
- Initial NVIDIA model is exactly `openai/gpt-oss-120b`.
- NVIDIA endpoint is exactly `https://integrate.api.nvidia.com/v1/chat/completions`.
- The real `NVIDIA_API_KEY` exists only in ignored `deploy/production.env`; tracked files contain an empty placeholder.
- No persistence migration, accounting-rule change, KDV-rule change, journal-balance change, or export-gate change is allowed.
- Commit, push, and deploy remain outside this plan's current authorization and require the project release gate.

## File Structure

- `backend/app/domain/openai_provider.py`: NVIDIA endpoint and default-model constants.
- `backend/app/workflows/document_processing.py`: NVIDIA provider construction and provider-chain acceptance.
- `backend/app/domain/production_readiness.py`: NVIDIA model/key readiness reporting.
- `backend/app/domain/ai_capacity.py`: NVIDIA document-agent configuration visibility.
- `backend/app/domain/ai_classification.py`: redact `nvapi-...` keys from semantic traces.
- `backend/tests/test_workflow_store.py`: runtime provider-order construction tests.
- `backend/tests/test_phase0_domain.py`: readiness, capacity, and secret-redaction tests.
- `docker-compose.production.yml`: pass NVIDIA configuration to backend and worker.
- `deploy/production.env.example`: tracked, empty NVIDIA configuration contract.
- `deploy/production.env`: ignored local paste location and NVIDIA-first trial order.

---

### Task 1: Add the NVIDIA runtime provider

**Files:**
- Modify: `backend/app/domain/openai_provider.py:14-24`
- Modify: `backend/app/workflows/document_processing.py:278-405`
- Test: `backend/tests/test_workflow_store.py:125-180`

**Interfaces:**
- Consumes: `ChatCompletionsAccountingProvider(api_key, model, chat_completions_url, provider_name, key_name)`.
- Produces: `_accounting_provider_from_env("nvidia", source)` and `SUPPORTED_ACCOUNTING_PROVIDERS` containing `nvidia`.

- [ ] **Step 1: Write the failing NVIDIA-first runtime test**

Add this test beside the existing provider-chain tests:

```python
def test_ai_runtime_from_env_builds_nvidia_first_provider_chain(self) -> None:
    runtime = build_ai_runtime_from_env(
        {
            "FISORA_AI_PROVIDER": "nvidia",
            "FISORA_AI_PROVIDER_CHAIN": "nvidia,groq,openrouter,cerebras",
            "NVIDIA_API_KEY": "nvapi-test-secret",
            "GROQ_API_KEY": "gsk-test",
            "OPENROUTER_API_KEY": "or-test",
            "CEREBRAS_API_KEY": "csk-test",
            "FISORA_NVIDIA_MODEL": "openai/gpt-oss-120b",
            "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
            "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
            "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
        }
    )

    provider = runtime["statement_ai_provider"]

    self.assertEqual(provider.provider_name, "nvidia>groq>openrouter>cerebras")
    self.assertEqual(provider.providers[0].provider_name, "nvidia")
    self.assertEqual(provider.providers[0].model, "openai/gpt-oss-120b")
    self.assertEqual(
        provider.providers[0].chat_completions_url,
        "https://integrate.api.nvidia.com/v1/chat/completions",
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_ai_runtime_from_env_builds_nvidia_first_provider_chain
```

Expected: FAIL because `nvidia` is filtered out of the provider chain.

- [ ] **Step 3: Add NVIDIA constants and factory construction**

In `openai_provider.py`, add:

```python
NVIDIA_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"
```

Import both constants in `document_processing.py`, then add this branch before `groq`:

```python
if provider_name == "nvidia":
    return ChatCompletionsAccountingProvider(
        api_key=source.get("NVIDIA_API_KEY", ""),
        model=source.get("FISORA_NVIDIA_MODEL", DEFAULT_NVIDIA_MODEL),
        chat_completions_url=source.get(
            "FISORA_NVIDIA_CHAT_COMPLETIONS_URL",
            NVIDIA_CHAT_COMPLETIONS_URL,
        ),
        provider_name="nvidia",
        key_name="NVIDIA_API_KEY",
    )
```

Change the supported set to:

```python
SUPPORTED_ACCOUNTING_PROVIDERS = {"openai", "groq", "openrouter", "cerebras", "nvidia"}
```

Add `nvidia` to the front of the canonical, classification, and counterparty `preferred_order` tuples so task-specific defaults do not silently move it behind another configured provider.

- [ ] **Step 4: Run the runtime test and existing provider-chain tests**

Run:

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_ai_runtime_from_env_builds_nvidia_first_provider_chain backend.tests.test_workflow_store.WorkflowStoreTests.test_ai_runtime_from_env_builds_three_provider_chain_for_fallback backend.tests.test_workflow_store.WorkflowStoreTests.test_ai_runtime_from_env_builds_provider_chain_for_fallback
```

Expected: 3 tests PASS.

---

### Task 2: Add readiness, capacity, and NVIDIA key redaction

**Files:**
- Modify: `backend/app/domain/production_readiness.py:9-85`
- Modify: `backend/app/domain/ai_capacity.py:8-143`
- Modify: `backend/app/domain/ai_classification.py:548-563`
- Test: `backend/tests/test_phase0_domain.py:152-194,404-460,8026-8060`

**Interfaces:**
- Consumes: `DEFAULT_NVIDIA_MODEL`, `PROVIDER_KEY_ENV`, `_provider_chain`, `_provider_model`, `serialize_semantic_decision_attempt`.
- Produces: readiness/capacity agents that report NVIDIA without exposing its key and semantic traces that redact `nvapi-...` values.

- [ ] **Step 1: Write failing readiness and capacity tests**

Add:

```python
def test_production_readiness_accepts_nvidia_first_ai_chain(self) -> None:
    env = {
        "FISORA_AI_PROVIDER": "nvidia",
        "FISORA_AI_PROVIDER_CHAIN": "nvidia,groq,openrouter,cerebras",
        "FISORA_NVIDIA_MODEL": "openai/gpt-oss-120b",
        "FISORA_GROQ_MODEL": "openai/gpt-oss-20b",
        "FISORA_OPENROUTER_MODEL": "openai/gpt-oss-20b:free",
        "FISORA_CEREBRAS_MODEL": "gpt-oss-120b",
        "NVIDIA_API_KEY": "nvapi-test-secret",
        "GROQ_API_KEY": "gsk-test",
        "OPENROUTER_API_KEY": "or-test",
        "CEREBRAS_API_KEY": "csk-test",
    }
    payload = production_readiness_payload(
        document_storage_path=self.temp_path / "documents",
        export_path=self.temp_path / "exports",
        backup_path=self.temp_path / "backups",
        env=env,
    )

    self.assertTrue(payload["ai_provider_configured"])
    self.assertEqual(payload["ai_provider"], "nvidia>groq>openrouter>cerebras")
    self.assertIn("openai/gpt-oss-120b", payload["ai_model"])

def test_ai_capacity_reports_nvidia_without_secret(self) -> None:
    payload = ai_capacity_payload(
        env={
            "FISORA_AI_PROVIDER_CHAIN": "nvidia,groq",
            "FISORA_NVIDIA_MODEL": "openai/gpt-oss-120b",
            "NVIDIA_API_KEY": "nvapi-test-secret",
            "GROQ_API_KEY": "gsk-test",
        }
    )

    self.assertTrue(payload["agents"][0]["configured"])
    self.assertEqual(payload["agents"][0]["model"], "openai/gpt-oss-120b")
    self.assertNotIn("nvapi-test-secret", str(payload))
```

- [ ] **Step 2: Write a failing trace-redaction test**

Extend the semantic-attempt credential test input with `NVIDIA_API_KEY=nvapi-private-123456` and assert:

```python
self.assertNotIn("nvapi-private-123456", serialized)
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_production_readiness_accepts_nvidia_first_ai_chain backend.tests.test_phase0_domain.Phase0DomainTests.test_ai_capacity_reports_nvidia_without_secret backend.tests.test_phase0_domain.Phase0DomainTests.test_semantic_attempt_redacts_json_credentials_and_full_authorization_values
```

Expected: at least readiness/capacity fail because NVIDIA is unsupported; the redaction assertion fails until `nvapi` is included.

- [ ] **Step 4: Implement NVIDIA readiness and capacity mappings**

Import `DEFAULT_NVIDIA_MODEL` in `production_readiness.py`. Add NVIDIA to `_ai_provider_model`, `_ai_provider_key_present`, and `supported_ai_providers`:

```python
if provider_name == "nvidia":
    return source.get("FISORA_NVIDIA_MODEL", "").strip() or DEFAULT_NVIDIA_MODEL
```

```python
"nvidia": "NVIDIA_API_KEY",
```

```python
supported_ai_providers = {"openai", "groq", "openrouter", "cerebras", "nvidia"}
```

In `ai_capacity.py`, add:

```python
"nvidia": "NVIDIA_API_KEY",
```

```python
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"
```

Update the supported provider filter and model selection:

```python
return [provider for provider in chain if provider in {"groq", "openrouter", "cerebras", "openai", "nvidia"}]
```

```python
if provider == "nvidia":
    return str(env.get("FISORA_NVIDIA_MODEL") or DEFAULT_NVIDIA_MODEL)
```

- [ ] **Step 5: Extend key-value redaction**

Change the key regex in `ai_classification.py` to include NVIDIA's prefix:

```python
API_KEY_VALUE_PATTERN = re.compile(r"(?i)\b(?:sk|gsk|csk|tvly|or-v1|nvapi)-[A-Za-z0-9._-]{6,}")
```

- [ ] **Step 6: Run focused and adjacent tests**

Run:

```powershell
python -m unittest backend.tests.test_phase0_domain.Phase0DomainTests.test_production_readiness_accepts_nvidia_first_ai_chain backend.tests.test_phase0_domain.Phase0DomainTests.test_production_readiness_warns_when_chain_provider_key_is_missing backend.tests.test_phase0_domain.Phase0DomainTests.test_ai_capacity_reports_nvidia_without_secret backend.tests.test_phase0_domain.Phase0DomainTests.test_ai_capacity_payload_reports_research_agent_configuration_without_keys backend.tests.test_phase0_domain.Phase0DomainTests.test_semantic_attempt_redacts_json_credentials_and_full_authorization_values
```

Expected: 5 tests PASS and no key value appears in payloads.

---

### Task 3: Wire Docker and prepare the safe paste location

**Files:**
- Modify: `docker-compose.production.yml:66-88,135-157`
- Modify: `deploy/production.env.example:34-59`
- Modify: `deploy/production.env` (ignored local file; never stage or print values)

**Interfaces:**
- Consumes: the runtime variables introduced in Tasks 1-2.
- Produces: identical NVIDIA configuration in backend and worker containers plus a local `NVIDIA_API_KEY=` paste slot.

- [ ] **Step 1: Add Compose environment forwarding to both services**

Add these entries next to the other provider settings in both backend and worker:

```yaml
FISORA_NVIDIA_MODEL: ${FISORA_NVIDIA_MODEL:-}
FISORA_NVIDIA_CHAT_COMPLETIONS_URL: ${FISORA_NVIDIA_CHAT_COMPLETIONS_URL:-}
NVIDIA_API_KEY: ${NVIDIA_API_KEY:-}
```

- [ ] **Step 2: Update the tracked example without a secret**

Use:

```env
FISORA_AI_PROVIDER=nvidia
FISORA_AI_PROVIDER_CHAIN=nvidia,groq,openrouter,cerebras
FISORA_NVIDIA_MODEL=openai/gpt-oss-120b
FISORA_NVIDIA_CHAT_COMPLETIONS_URL=https://integrate.api.nvidia.com/v1/chat/completions
NVIDIA_API_KEY=
```

Keep all other provider keys empty in this tracked file.

- [ ] **Step 3: Prepare the ignored local production file**

Change only the non-secret provider order and add the NVIDIA fields:

```env
FISORA_AI_PROVIDER=nvidia
FISORA_AI_PROVIDER_CHAIN=nvidia,groq,openrouter,cerebras
FISORA_NVIDIA_MODEL=openai/gpt-oss-120b
FISORA_NVIDIA_CHAT_COMPLETIONS_URL=https://integrate.api.nvidia.com/v1/chat/completions
NVIDIA_API_KEY=
```

Do not echo or rewrite existing provider secrets. The user pastes the NVIDIA key after the equals sign locally.

- [ ] **Step 4: Validate rendered Compose variables without printing secrets**

Run:

```powershell
docker compose --env-file deploy/production.env -f docker-compose.production.yml config | Select-String 'FISORA_AI_PROVIDER:|FISORA_AI_PROVIDER_CHAIN:|FISORA_NVIDIA_MODEL:|FISORA_NVIDIA_CHAT_COMPLETIONS_URL:'
```

Then check presence only:

```powershell
$line = Get-Content -Encoding utf8 deploy/production.env | Where-Object { $_ -match '^NVIDIA_API_KEY=' }
if ($line) { 'NVIDIA key slot var' } else { 'NVIDIA key slot eksik' }
```

Expected: NVIDIA is first in the provider chain, endpoint/model appear for backend and worker, and the key slot is present without its value being printed.

---

### Task 4: Verify the provider boundary and accounting safety

**Files:**
- Verify only: changed files from Tasks 1-3.

**Interfaces:**
- Consumes: the NVIDIA runtime/configuration implementation.
- Produces: local evidence that provider selection changed while accounting and export controls did not.

- [ ] **Step 1: Run targeted provider/readiness tests**

```powershell
python -m unittest backend.tests.test_workflow_store.WorkflowStoreTests.test_ai_runtime_from_env_builds_nvidia_first_provider_chain backend.tests.test_phase0_domain.Phase0DomainTests.test_production_readiness_accepts_nvidia_first_ai_chain backend.tests.test_phase0_domain.Phase0DomainTests.test_ai_capacity_reports_nvidia_without_secret backend.tests.test_phase0_domain.Phase0DomainTests.test_semantic_attempt_redacts_json_credentials_and_full_authorization_values
```

Expected: 4 tests PASS.

- [ ] **Step 2: Run the stable local proof set**

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

Expected: backend and frontend tests PASS, frontend build succeeds, and diff check is clean. Report PostgreSQL DSN-gated skips separately.

- [ ] **Step 3: Inspect scope and secrets**

```powershell
git status --short
git diff -- backend/app/domain/openai_provider.py backend/app/workflows/document_processing.py backend/app/domain/production_readiness.py backend/app/domain/ai_capacity.py backend/app/domain/ai_classification.py backend/tests/test_workflow_store.py backend/tests/test_phase0_domain.py docker-compose.production.yml deploy/production.env.example docs/superpowers/specs/2026-07-22-nvidia-primary-ai-provider-design.md docs/superpowers/plans/2026-07-22-nvidia-primary-ai-provider.md
```

Expected: only intentional tracked changes appear; `deploy/production.env` remains ignored and no `nvapi-` secret appears in the diff.

- [ ] **Step 4: Optional real-key smoke after the user pastes the key**

Do not run a paid/external provider call until the key is present and the user has approved the smoke. When approved, use a minimal structured classification request through `build_ai_runtime_from_env`, print provider/model plus response shape only, and never print request headers or the key.

Expected: provider is `nvidia>groq>openrouter>cerebras`, the first successful result is structured JSON, and deterministic KDV/balance/export gates remain downstream and unchanged.
