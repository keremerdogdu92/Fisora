# Gemini integration and evaluation notes

## Current status — 2026-09-19

The original notes below were prepared before the production Rule Harness benchmark and rollout. The current canonical runtime is `backend/app/services/learned_rule_audit_shadow.py`, prompt version `learned-rule-audit-shadow-v4-20260918`, using the fixed three-stage flow: search plan -> host search -> candidate selection/open -> final row audit. The production model does not load this Markdown file dynamically.

The procedure has since been benchmarked with Gemini 3.5 Flash-Lite and deployed in the accountant pilot. See `docs/current-handoff-2026-09-18-rule-harness-experiments.md` for measured benchmark results and architecture decisions. Treat statements below that say the procedure "has not been benchmarked" as historical context from the pre-benchmark draft.

Prepared 2026-09-18. Target requested by user: `gemini-3.5-flash-lite`.

## Deployment contract

This is a reusable Gemini audit procedure in skill packaging, not an installed Codex skill. Send the body of SKILL.md (without YAML frontmatter) as the system instruction on every audit call. A file name or skill name alone does not load its contents into Gemini.

Send invoice context, stable row IDs, draft accounts, and optional host budgets as structured user input. Keep the complete procedure present across the tool loop. End the input with: "Audit every supplied row using the learned-rule-audit procedure. Return the required JSON result."

The actual search_rules/get_rule schemas and production output schema were not supplied or inspected. Adapt field names/types to those schemas before deployment; do not add unsupported tool parameters. Listing/pagination instructions apply only when exposed by the tools.

The proposed output envelope intentionally extends the original corrections-only contract. Store row_audits as audit telemetry; pass only validated corrections to the existing accounting consumer. Do not silently discard incomplete status. If the consumer cannot accept an envelope, the orchestrator must provide an equivalent separate coverage/error channel. A corrections-only array cannot distinguish successful no-change from incomplete work by itself.

## Enforcement in the host

- Validate row IDs as a multiset against input, not just row count. Reject omissions, duplicates, and unknown rows.
- Keep actual tool-call evidence server-side. Verify reported queries and opened_rule_ids against successful calls; self-reported evidence is not proof.
- Require every correction's rule_id to be in the successful get_rule results for this audit; verify the prescribed account, from_account, and permitted field set against source data.
- Revalidate rule applicability/conflicts where the rule format supports deterministic checks. Merely opening a rule does not make it applicable.
- Preserve all tool results and any protocol-required model continuation data across turns. Do not terminate the tool loop after the first search or the first get_rule.
- Derive completion from row outcomes and evidence, not from the model's audit_status alone. On incomplete, retry affected rows or surface them for review according to product policy.
- Bound total calls/time separately. On timeout, truncation, malformed output, or exhausted tool-loop budget, record an incomplete run; never substitute an empty successful corrections array.
- For larger invoices, partition by stable row IDs into bounded batches while preserving invoice context and aggregate coverage in the host. Determine batch size from evaluation rather than the advertised context limit.

The three-query negative-search threshold and six-query/three-page default budget are initial design choices, not Google requirements or measured optima. Tune them using recall, false corrections, unresolved rate, latency, and tool cost. Relevant unvisited leads imply unresolved even if a numerical minimum was met.

## Model guidance verified from primary sources

- The model page lists `gemini-3.5-flash-lite` and support for function calling, structured outputs, and thinking: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- Google recommends direct, consistently structured Gemini 3 instructions, critical constraints in system instructions, and default sampling parameters for Gemini 3.x. Start with defaults rather than automatically setting temperature to zero: https://ai.google.dev/gemini-api/docs/prompting-strategies
- Tool schemas need precise descriptions and typed parameters. Do not require prose/JSON progress messages before each tool call. Function-calling modes constrain call behavior but do not establish row coverage: https://ai.google.dev/gemini-api/docs/function-calling
- Use the supported JSON Schema subset for the final envelope. Schema-conforming JSON still requires application-level value validation: https://ai.google.dev/gemini-api/docs/structured-output

This procedure is an engineering adaptation of those recommendations. It has not been benchmarked against Gemini or production invoice/rule data. No claim that English outperforms Turkish is made; English is retained to match the existing prompt and tool interface. Preserve Turkish invoice terminology in searches.

## Behavioral evaluation before release

Compare the old and new procedures on the same held-out invoices and a fixed rule-store snapshot. Repeat cases to measure variability. Test at least:

| Case | Required behavior |
| --- | --- |
| Relevant rule only for the last of many rows | Last row inspected and correction found |
| Long item description misses; short family query succeeds | Retry and open matching rule |
| Abbreviation in invoice, expanded form in rule | Supported alternate query finds candidate |
| Relevant candidate on another page | Continue or narrow; do not prematurely return no match |
| Same supplier, unrelated service | Reject the superficially similar rule |
| Draft account already matches an applicable rule | Open rule; confirmed_unchanged, no correction |
| No relevant rule after complete search | no_applicable_rule_found, no invented account |
| Unknown prerequisite, two conflicting rules, or missing draft mapping | unresolved; audit incomplete |
| Search error, get_rule error, timeout, or unvisited lead at budget | Incomplete rather than successful empty result |
| Equivalent descriptions with different applicability context | Separate applicability checks |
| Mixed-component row needing separate accounts | unresolved; no amount changes or row splits |
| Unconfirmed/inactive rule | No correction based on that rule |

Measure row coverage, missed required corrections, false corrections, successful get_rule citation rate, incomplete-run handling, calls per row, and latency. Do not accept a recall gain obtained by increasing unsupported corrections.