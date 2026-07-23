# NVIDIA Primary AI Provider Design

## Goal

Add NVIDIA API Catalog as Fisero's primary accounting AI provider for an initial reversible trial. Preserve Groq, OpenRouter, and Cerebras as automatic fallbacks.

## Provider order

The configured accounting provider chain will be:

```text
nvidia -> groq -> openrouter -> cerebras
```

NVIDIA will use its OpenAI-compatible chat-completions endpoint. The initial model will be `openai/gpt-oss-120b`, matching Fisero's existing comparison-model family. Changing the order or model later will require environment configuration only.

## Runtime configuration

The ignored local production environment file will expose:

```env
FISORA_AI_PROVIDER=nvidia
FISORA_AI_PROVIDER_CHAIN=nvidia,groq,openrouter,cerebras
FISORA_NVIDIA_MODEL=openai/gpt-oss-120b
FISORA_NVIDIA_CHAT_COMPLETIONS_URL=https://integrate.api.nvidia.com/v1/chat/completions
NVIDIA_API_KEY=
```

The real key will only be pasted into `deploy/production.env`. It will not be placed in tracked examples, documentation, logs, tests, or chat. The tracked example will contain an empty placeholder.

## Code and deployment flow

The provider factory will construct NVIDIA through the existing OpenAI-compatible `ChatCompletionsAccountingProvider`. Provider-chain validation, readiness reporting, capacity status, Docker Compose environment forwarding, and tests will recognize `nvidia` explicitly.

At runtime, Fisero will try NVIDIA first. Only a provider failure will advance to the existing providers in order; no deterministic accounting or export guard will change.

## Failure handling and reversibility

- A missing NVIDIA key must be reported as a configuration/readiness failure.
- An NVIDIA request error must be recorded with the provider name and then permit the existing fallback behavior.
- Secrets must remain redacted from traces and error messages.
- Reverting the trial requires changing `FISORA_AI_PROVIDER` and `FISORA_AI_PROVIDER_CHAIN`; no migration or stored-data rewrite is involved.

## Verification

1. Unit tests prove NVIDIA runtime construction, provider ordering, missing-key readiness, and fallback behavior.
2. Compose inspection proves NVIDIA variables reach backend and worker containers.
3. A local smoke uses the user-supplied key without printing it and confirms a structured response from `openai/gpt-oss-120b`.
4. Existing targeted provider and readiness tests remain green.

Production deployment is outside this local configuration step and still requires the separate commit, push, and deploy approval gate.
