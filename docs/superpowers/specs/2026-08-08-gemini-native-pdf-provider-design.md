# Gemini Native-PDF Accounting Provider Design

## Decision

Fisero admits Google Gemini as an active accounting provider for every AI task. The default model is `gemini-2.5-flash-lite`. Gemini is first in the configured and task-specific chains, while the existing providers remain bounded fallbacks.

The user explicitly accepts using the unpaid Gemini API with authorized real Fisero documents under Google's current unpaid-service data terms. The API key must come directly from Google AI Studio and must never be committed, printed, or placed in tracked configuration.

## Provider boundary

Create a dedicated `GeminiAccountingProvider` using the native Gemini `generateContent` REST contract:

- endpoint: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`;
- authentication: `x-goog-api-key: GEMINI_API_KEY`;
- structured output: `generationConfig.responseMimeType=application/json` and `responseJsonSchema`;
- canonical PDF input: inline base64 bytes with MIME type `application/pdf`;
- semantic account, counterparty, statement, and learning inputs: JSON text parts under the same structured-output contract.

`CanonicalExtractionRequest` carries optional PDF bytes as a non-repr, non-schema field. Generic fallback providers continue to consume only `document_text`; therefore Gemini can fail over without teaching other adapters about binary input.

## PDF flow

`parse_pdf_invoice` retains deterministic text, identity, line, VAT, and total extraction. When canonical AI runs, it sends the original PDF bytes to Gemini together with the deterministic payload, tenant identity, observation-only instructions, and output schema. Gemini observations remain subject to canonical line binding, deterministic arithmetic, VAT reconciliation, source evidence, and export gates.

This first implementation does not replace deterministic parsing and does not make a successful API call equivalent to accounting correctness. Native PDF input supplies visual/layout evidence; deterministic code remains authoritative for safety and export.

Inline PDF input is capped at 50,000,000 bytes. Oversize documents raise a provider error and use the existing fallback chain. The Files API, resumable uploads, caching, and multi-turn file reuse are outside this scope.

## Configuration and routing

Tracked configuration exposes empty/default variables only:

```text
FISORA_AI_PROVIDER=gemini
FISORA_AI_PROVIDER_CHAIN=gemini,nvidia,groq,cerebras,cloudflare,sambanova,openrouter
FISORA_GEMINI_MODEL=gemini-2.5-flash-lite
FISORA_GEMINI_GENERATE_CONTENT_URL=
FISORA_GEMINI_TIMEOUT_SECONDS=60
FISORA_GEMINI_MAX_OUTPUT_TOKENS=16384
FISORA_GEMINI_MAX_INLINE_PDF_BYTES=50000000
GEMINI_API_KEY=
```

Backend and worker containers receive these variables. Readiness and capacity surfaces recognize `gemini`, expose only key presence, and never expose the key value. Trace redaction recognizes Google API-key shapes.

## Canonical decision update

The canonical decision register will replace the old benchmark-only/billing-required Gemini restriction with the approved active-use decision. It will preserve these boundaries:

- unpaid Gemini may receive authorized real development and operational Fisero documents;
- current unpaid-service data-use and possible human-review behavior is explicitly accepted;
- provider output is semantic/source-observation input only;
- tenant authorization, canonical evidence, VAT, balance, account-candidate, accountant override, and export gates remain deterministic and independent;
- FreeLLM remains a discovery catalog and never receives prompts, documents, or API keys.

## Verification contract

- Unit/domain RED-GREEN proof for native PDF body, JSON schema, authentication, response parsing, size limit, factory construction, routing, readiness, capacity, and redaction.
- Existing canonical PDF tests prove provider output cannot overwrite deterministic line identity or money.
- Compose config proves Gemini variables reach backend and worker.
- A real Gemini smoke uses a generated synthetic PDF first and records only status/model/timing/schema-validity, never the key or raw sensitive content.
- A user-authorized real PDF can then be inspected field-by-field; success requires canonical source evidence, reconciled VAT/totals, explicit AI-used/rejected state, and safe export status.

## Release boundary

Implementation and local verification are authorized. Commit, push, production secret installation, and deploy remain a separate release transaction requiring explicit approval.
