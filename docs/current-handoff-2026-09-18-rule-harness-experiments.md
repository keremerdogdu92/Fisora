# Fisora Rule Harness Experiments Handoff — 2026-09-18

## Purpose

This handoff records the Rule Harness architecture, scale experiments, provider/model comparisons, cost findings, and the exact open problem after the 2026-09-17/18 session.

It supplements `docs/current-handoff-2026-09-17-ai-accounting-model-experiments.md`. Production was not changed by these Rule Harness experiments.

## Architecture decision

The learned-rule system should not dump hundreds/thousands of rules into the model prompt and should not rely on the old deterministic best-score/top-k rule selector as accounting authority.

Target shape:

`invoice + Planner + draft account choices -> Rule Harness -> deterministic validation/compiler`

The Rule Harness is a constrained rule auditor, not a second full accountant.

It may:
- search the learned rule store,
- open candidate rules,
- return account-only corrections backed by explicit rule IDs.

It must not change:
- amounts,
- debit/credit direction,
- taxes,
- counterparty,
- payable,
- source rows.

Search ranking is recall only. A returned result is not authority until the model opens and semantically validates the rule.
## Existing rule subsystem to reuse

This is not greenfield. Existing code already provides versioned tenant-scoped rules and deterministic authority checks.

Important files:
- `backend/app/services/learning_rule_service.py`
- `backend/app/persistence/learning_rule_repository.py`
- `backend/app/api/phase0_routes_learning_rules.py`
- `backend/app/domain/learning_rules.py`
- `backend/app/domain/verified_rule_authority.py`
- `backend/app/domain/natural_language_rule_builder.py`
- `backend/app/domain/research_harness.py`

The old brittle runtime is mainly `learning_rules.py`, which computes a score, applies a threshold, sorts, and selects the best rule. That runtime should be replaced/demoted for learned-rule selection.

`verified_rule_authority.py` remains useful after the model chooses a rule: validate active/evidenced status, client/direction/mode, chart membership, scope, and conflicts before applying a patch.

Rule learning remains:
- accountant explicit teaching,
- accountant corrections that may become reusable rules after confirmation,
- possible model fine-tuning only later.

Explicit accountant-taught rule > approved correction-derived rule > base-model judgment.
## Rule Harness lab design

Initial lab tools:
- `search_rules(query, direction, offset)`
- `get_rule(rule_id)`
- `list_rules(direction, offset)`

The model does not see the full rule store. Search returns summaries; `get_rule` opens full rule meaning/scope.

A Rule Harness job can contain several model turns:
`AI -> search -> AI -> get_rule -> AI -> finish`

Therefore one logical harness run is not necessarily one underlying inference call.

Hard guards used in the lab:
- correction row must exist,
- cited rule must have been opened,
- target account must equal the opened rule account,
- from-account must match the current draft,
- target account must exist in the chart.

Final deterministic compiler/validator runs after patches.

Core lab files created under ignored `tmp/`:
- `benchmark_rule_harness_same7_20260917.py`
- `benchmark_rule_harness_scale_20260917.py`
- `benchmark_rule_harness_openrouter_0731_same7_20260917.py`
- `benchmark_rule_harness_groq_cloudflare_same7_20260917.py`
- `benchmark_rule_harness_gemini_flashlite_same7_20260917.py`
- `benchmark_rule_harness_gemini_flashlite_scale_20260917.py`
## First Rule Harness result — DeepSeek, 19 rules

Same fixed 7 real HTML invoices. One plausible account decision was intentionally corrupted per invoice. Rule store contained 7 target learned rules + 12 distractors.

Result:
- 7/7 successful,
- average harness latency ~10.6 s/document,
- 23 model calls total (~3.3 turns/document),
- 49,294 tokens total (~7,042/document),
- zero false corrections,
- zero guard errors.

Important behavior:
- rental search returned a generic rental distractor before the correct SECOM rental rule; model still chose the correct rule,
- warranty case first opened a generic repair rule, then refined search and found the specific Xceed amplifier rule.

This established that agentic rule navigation works on a small store without injecting all rules into context.

## Scale result — DeepSeek

Real set expanded to 20 invoices including 11-row, 9-row, 6-row and 5-row documents.

100 rules:
- functionally 20/20 after separating provider JSON errors / equivalent duplicate-rule IDs,
- ~12.4 s average,
- ~10.3k tokens average.

500 rules:
- approximately 19/20 functional,
- ~11.8 s average,
- ~10.9k tokens average.

The main real retrieval miss was a Widex MRR4D Charger rule: the correct learned rule existed but DeepSeek failed to retrieve/open it.
## Multi-row / large-store DeepSeek stress

Five highest-row-count invoices were tested with much larger stores.

2,000 rules:
- 5/5 functionally correct after retrying structured-output failures,
- ~18.6 s average,
- ~18.3k tokens average.

10,000-rule stress:
- first 11-row invoice passed at ~22.9 s / ~21.5k tokens / 6 turns.
- The key architectural signal was that rule-store growth did not linearly increase context/token use because only search results are shown to the model.

Main scaling problem is therefore not prompt context size. It is rule-search recall and search strategy.

Structured-output reliability also matters: direct DeepSeek occasionally returned malformed JSON; retries recovered the cases.

## Luna comparison

Old account-only 7-invoice benchmark:
- DeepSeek 7/7, ~11.5 s average,
- Luna 7/7, ~13.8 s average,
- both matched 28/28 expected business/tax choices.

Rule Harness representative 5-case / 100-rule comparison:
- DeepSeek 5/5, ~16.1 s average, ~14.5k tokens,
- Luna 5/5 with tolerant parser, ~103.9 s average, ~9.3k tokens.

Luna often used fewer tokens and fewer turns but was dramatically slower.
Luna also found the difficult MRR4D Charger rule at 500 rules where DeepSeek missed it, but required ~231.9 s.

Luna structured JSON was unstable with the strict parser (frequent extra-data formatting). A tolerant first-valid-JSON parser recovered semantic correctness.

Conclusion: Luna is useful as a benchmark/reference model for difficult retrieval, but current latency makes it unattractive as the universal runtime Rule Harness.

## OpenRouter DeepSeek V4 Flash 0731

Existing OpenRouter key successfully called `deepseek/deepseek-v4-flash-0731`.

Same 7 Rule Harness invoices:
- 6/7 functional success,
- ~37.7 s average,
- ~6.2k tokens average,
- warranty/Xceed amplifier rule was missed.

A 20-invoice/500-rule scale attempt became impractically slow; first large case exceeded several minutes and the run was stopped.

Conclusion: very cheap, but slower and weaker than current V4.1/direct DeepSeek for this task.

OpenRouter V4.1 Flash could not be benchmarked with the current account because the route returned 402/payment-required.

## Other providers

Existing keys were smoke-tested:
- Groq GPT-OSS-20B: tiny structured smoke was fast (~0.6 s), but real Rule Harness requests failed with API/tool-protocol 400 and later 429.
- Cloudflare GPT-OSS-120B: tiny structured smoke worked (~2.9 s); real harness mostly emitted reasoning with empty content / malformed JSON. Only 1/7 passed under the current adapter.
- Cerebras: 402/payment required.
- SambaNova: read timeout.
- NVIDIA: 410 Gone for the configured route.

These were adapter/provider compatibility results, not definitive model-quality rankings.
## Gemini 3.5 Flash-Lite — strongest new candidate

The existing Gemini project pool already uses `gemini-3.5-flash-lite` for Planner. It was tested directly as Rule Harness.

Same 7 original Rule Harness invoices:
- 7/7 functional success,
- 0 provider/JSON errors,
- ~3.39 s average,
- ~4.04k tokens average,
- exactly 3 model turns average,
- difficult warranty case passed in ~3.4 s.

This was substantially faster and cheaper than DeepSeek/Luna in the small set.

Scale test, 20 invoices / 500 rules:
- 15/20 on the first prompt,
- 0 provider errors,
- ~3.31 s average,
- ~4.48k tokens average.

Importantly, Gemini found and applied the MRR4D Charger rule that DeepSeek had missed.

The five misses were mostly not bad search ranking. Gemini often stopped early and declared no learned rule without searching every distinct row/family.
A temporary stronger instruction requiring at least one search and full coverage was tested only on the five failed 500-rule cases:
- 4/5 recovered,
- postal/Yurtiçi cases recovered,
- two sales cases recovered,
- only the multi-row warranty/Xceed case still failed.

The remaining failure is highly diagnostic:
- Gemini searched/opened the general Demant/Oticon repair rule,
- decided other rows looked plausibly classified,
- did not separately search the `AMPLIFIER XCEED` row,
- therefore missed the specific learned rule `AMPLIFIER XCEED -> 153.01`.

So the next problem is row/family coverage, not forcing a rule to exist.

Correct behavioral requirement:
- a learned rule is NOT guaranteed to exist,
- no rule should ever be invented or forced,
- every distinct row/product/service family must be checked,
- if even one applicable learned rule exists, it must be applied,
- equivalent repeated rows may share one search,
- an empty result is valid only after complete coverage.

Do not blindly require a correction. Require complete search coverage.

## Prompt status

The original harness prompt is small: ~155 words / 1,014 characters.

A much larger rewrite was discussed but rejected as unnecessarily verbose. The next prompt should preserve the original compact structure and add only the missing coverage guarantees.

The exact new prompt is intentionally not frozen in this handoff; continue from the latest Codex/Astra discussion when connected to the home computer.
## Cost findings

At the user's expected near-term volume (~4,000–5,000 documents/month), model cost is not currently the primary constraint; latency and correctness are more important.

Approximate earlier calculations, assuming Rule Harness runs on every document:
- Luna/xKiro Rule Harness only: ~$4.6–5.8/month.
- Direct DeepSeek V4.1 Rule Harness only: roughly ~$8.7–10.9/month at off-peak pricing, roughly double at peak.
- Planner + account-call + Rule Harness with DeepSeek off-peak was estimated around ~$28–35/month total at 4k–5k documents; continuous peak pricing roughly ~$49–61/month.

OpenRouter V4 Flash 0731 was much cheaper on token price, but its latency/quality tradeoff was poor in our real benchmark.

Recalculate before production decisions because provider pricing can change.

## Current production status vs lab

Production was NOT changed during these experiments.

Production hotfix remains:
`22f3499ffe47066537d182b90a8e2b3e94cb7c63`

Final Accountant currently uses direct DeepSeek after the XKIRO DeepSeek alias removal.

The Rule Harness, Gemini Flash-Lite runtime choice, compact new prompt, and account-only architecture are still experiments unless another later chat explicitly integrated/deployed them.

## Exact next work

1. Connect to the home computer through OpenRemote and inspect the latest Codex conversation; the user says the latest prompt work is open there.
2. Do not reconstruct/overwrite that prompt from this handoff if Codex already has a newer version.
3. Freeze a compact coverage-aware prompt before benchmarking.
4. Re-run Gemini Flash-Lite on the difficult warranty case first.
5. Then run the same 20 invoices / 500 rules.
6. Then run the five multi-row invoices / 2,000 rules.
7. Measure functional success, correct no-rule behavior, rule seen/opened/applied, false corrections, conflicts, model turns, latency and tokens.
8. Add explicit no-rule and conflicting-rule cases before claiming production readiness.
9. If correctness holds, adapt real active rows from `LearningRuleRepository` into harness tools and use `verified_rule_authority.py` as deterministic post-selection gate.
10. Keep production feature-flagged until the lab is stable.

Do not stage, commit, push or deploy unrelated dirty work while continuing these experiments.
