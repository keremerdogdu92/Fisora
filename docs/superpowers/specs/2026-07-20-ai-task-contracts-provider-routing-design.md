# AI Task Contracts and Provider Routing Design

## Accepted scope

- UBL/XML remains the primary canonical accounting source.
- PDF fallback supports two explicit AI modes: `discovery` for source lines the deterministic parser did not establish and `repair` for already anchored canonical lines.
- AI observes document values and makes semantic accounting choices; deterministic code owns identity, arithmetic, VAT, balance, line coverage, and export eligibility.
- Prompt instructions are short and task-specific. Structured output schemas remain API contracts rather than conversational instructions whenever the provider supports strict structured output.
- Provider order is task-aware: canonical PDF work prefers `cerebras,groq,openrouter`; semantic account work prefers `groq,cerebras,openrouter`; counterparty resolution prefers `cerebras,groq,openrouter`. Only providers already configured in the base chain are reordered.
- Tavily remains uncertainty-triggered research and is not called for every document.

## PDF modes

### Repair

Repair is selected when deterministic PDF extraction already established canonical source lines but left fields incomplete. The provider must echo every supplied `canonical_line_id` exactly once. Server source positions and any already trusted observed values win.

### Discovery

Discovery is selected when no line exists or canonical totals show that the existing extracted line set is incomplete or inconsistent. The provider returns every observed invoice row with a non-empty source position and no authoritative provider line identity. Fisero rejects duplicate/missing source positions, clears provider-supplied IDs, and generates stable canonical IDs from the trusted PDF source locator.

Discovery output is accepted only after deterministic arithmetic, canonical validation, and unique line/source coverage succeed. Failure preserves the original deterministic result with an actionable extraction note.

## Task prompts

- `document_discovery`: observe all printed invoice rows and source positions; do not calculate or make accounting decisions.
- `document_repair`: complete only supplied canonical rows; do not add, remove, merge, calculate, or rewrite IDs.
- `account_family_select`: choose relevant real chart families.
- `line_account_decision`: choose semantic meaning and a real account for every canonical line ID.
- `counterparty_resolve`: resolve only the current real counterparty candidates or state that a new counterparty is needed.

## Routing

The runtime builds separate chains from the configured base provider membership. Task-specific environment variables may override order without adding an unconfigured provider. Classification routing selects the counterparty chain only for `counterparty_resolve`; other semantic stages use the classification chain. Canonical extraction always uses the canonical chain.

## Safety and acceptance

- UBL behavior is unchanged.
- Provider-generated discovery IDs are never authoritative.
- Repair exact-ID coverage remains mandatory.
- Discovery requires non-empty, unique source positions and at least one line.
- AI cannot overwrite deterministic invoice mathematics.
- Schema-invalid provider output is a failure and falls through to the next configured provider.
- Prompt/provider/schema versions and task stage remain visible in existing trace evidence.
- Targeted contract tests must pass before the stable backend suite is run.
- Real accounting/provider admission still requires the protected 35-purchase/15-sales accountant-reference corpus.

## Non-scope for this slice

- Changing UBL canonical parsing.
- Admitting a new provider.
- Final numeric timeout/circuit-breaker calibration; these require real task latency evidence.
- Commit, push, deploy, or production reprocessing.
