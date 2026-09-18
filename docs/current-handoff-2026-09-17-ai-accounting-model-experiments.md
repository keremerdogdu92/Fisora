# Fisora AI Accounting Model Experiments Handoff — 2026-09-17

## Purpose
This handoff consolidates the accounting-model experiments, provider findings, production hotfix, and the exact next tests. It is intended to let a new chat continue without reconstructing this conversation.

## Current production baseline
- Canonical flow remains: source reader -> semantic/identity planner -> Final Accountant -> deterministic validation/projection.
- HTML is increasingly the preferred accountant happy path when eligible; PDF remains supported/fallback.
- The production Final Accountant prompt still performs a broad task: interpret economic meaning, posting basis, taxes/discounts, choose exact chart accounts, create journal lines, counterparty line, source coverage, and balanced output.
- The production model had been `deepseek/deepseek-v4-flash` through XKIRO.
- XKIRO removed that exact model alias from the current model list, which broke the live final-accountant path.

## Production hotfix completed
- Direct DeepSeek API was already configured locally and the production env was confirmed to contain `DEEPSEEK_API_KEY`.
- Direct model: `deepseek-v4-flash`.
- Best direct settings found: thinking enabled, `reasoning_effort=low`, `max_tokens=16384`, timeout 120s.
- `thinking=disabled` returned quickly but materially reduced accounting quality.
- Default/high thinking often consumed the output budget and returned reasoning with empty final JSON on complex invoices.
- With low reasoning, 3 real production Final Accountant cases passed: Yurtiçi Kargo, complex TTNET, Erkan sale.
- Clean HTML production-path smoke also produced a balanced 238.69 / 238.69 journal using provider=`deepseek`.
- Hotfix commit: `22f3499ffe47066537d182b90a8e2b3e94cb7c63` (`[deploy] restore final accountant via direct DeepSeek`).
- Production HEAD was verified at this exact SHA after deploy.
- Backend/frontend healthy after restart.
- Live container smoke verified: provider=`deepseek`, model=`deepseek-v4-flash`, low reasoning, 16K output, structured JSON response OK.

## Model/provider observations
### DeepSeek
- Old single-shot Final Accountant benchmark: strongest model; `deepseek/deepseek-v4-flash` previously achieved 6/6 strict on the core real-invoice set.
- `deepseek-v4.1-flash` also previously completed 6/6 in benchmark, around 31s average, but XKIRO now exposes it as premium wallet-only.
- XKIRO currently has no free DeepSeek route usable as the old production alias.
- Direct DeepSeek preserves the same underlying V4 Flash model and is now the production recovery path.

### Luna
- Weak/unstable when asked to do the entire old Final Accountant task in one large call.
- Strong when the task is narrowed.
- Earlier narrow account-selector experiment reached 6/6 on QNB/TTNET/TT Mobil repeats.
- Deterministic amount/component handling + Luna only for account selection reached 9/9 aggregate in the small three-invoice repeat test, with much lower token use and latency.
- Two-Luna split (semantic -> account selection) works on real invoices, but the semantic output can anchor the second call incorrectly and complex invoices can become slow.

### Kimi
- Kimi K2.5/K2.6 was better in the old single-shot Final Accountant benchmark than initially remembered.
- K2.6 had runs with 4/6 strict among completed invoices; provider 429s reduced completion reliability.
- In HTML split tests, Kimi produced clean balanced journals when XKIRO returned a response and was often faster than Luna.
- Still needs the new direct-account-only benchmark; provider stability was the main blocker, not a proven accounting-quality failure.
## Experiment families already tried
1. **Old one-call Final Accountant**: Reader + Planner -> one model performs almost all accounting reasoning and emits the final journal. DeepSeek strongest; Luna weaker; Kimi sometimes strong but less stable.
2. **Narrow account selection**: model only selects accounts after amounts/meaning are prepared. Luna improved dramatically.
3. **Two-stage Luna**: first reconcile/interpret components, then select accounts. Arithmetic/reconciliation errors remained on TTNET/TT Mobil.
4. **Deterministic amounts + account-only Luna**: strongest small Luna result, but an early version manually narrowed the chart to about 30 broad-family accounts, so it was not a fully fair full-chart test.
5. **Fine-grained deterministic component expansion**: caused policy problems by turning settlement/ancillary adjustments into journal lines too aggressively.
6. **Real PDF -> Reader -> Luna semantic -> Luna account -> compiler**: Bera repair and MOXI matched the expected accounting family; Metro correctly understood products and initially left ambiguous expense accounts for review.
7. **Best-effort split prompt**: changed account selection to always choose the most plausible real account and mark `needs_review=true` rather than leave it blank. Metro then produced plausible cleaning/personnel-food/packaging selections with review flags.
8. **HTML -> Planner -> semantic/account split -> compiler**: demonstrated that HTML gives cleaner authoritative row amount/VAT structure than PDF, but Luna became slow on multi-row documents and XKIRO 429/500 made cross-model comparison noisy.
9. **Proposed current experiment: direct account-only call**: raw HTML row + client/counterparty/planner context + full real detail chart -> one AI call only chooses the best account (and review flag). No separate semantic output and no journal arithmetic inside the model. This specific full-chart HTML benchmark has NOT yet been completed because XKIRO failures interrupted it.

## Important real examples
- Bera repair: model should understand out-of-warranty hearing-device repair / receiver replacement; strong result was `740.01.001 Tamir Bakım Bedeli` plus purchase VAT.
- Bera MOXI + receivers: Luna split selected `153.01.001` for device and receiver inventory; balanced 22,134.24 journal in test.
- Metro mixed basket: soap, biscuits/cakes, soda, plastic bag. Product identity was understood well; business purpose remains genuinely ambiguous for food/drink and packaging, so review is appropriate even if a best-effort account is selected.
- `SLIM TAPER`: dangerous ambiguity example. With hearing-center context Luna once inferred a hearing-device accessory, while the intended hypothetical correction was trousers/apparel. This shows why intermediate semantic guesses can anchor later calls.
- QNB eSolutions `TEK KONTÖR`: old benchmark gold `770.02.002 Haberleşme` is likely semantically questionable; QNB kontör relates to e-document services. Do not treat old gold labels as unquestionable truth.
- TTNET: complex example with internet/access/VAS/device, discounts, late fee, VAT, ÖİV, previous/next-period settlement differences. Printed payable 1150.75; useful for testing exact final balance and adjustment policy.
## HTML vs PDF findings
- Recent experiments were initially PDF-heavy because the real PDF set was easy to exercise through the existing source reader.
- The accountant workflow has moved toward HTML as happy path when HTML accounting eligibility passes.
- HTML source processing is deterministic before Planner/Final Accountant and exposes table columns structurally.
- This is preferable for compiler inputs because row amount, VAT rate, VAT amount, and printed totals can be normalized from explicit columns instead of inferred visually.
- A prototype bug demonstrated the rule: custom test code looked only for `Mal Hizmet Tutarı`, while another HTML used `Malzeme / Hizmet Tutarı`; it then accidentally treated VAT as line amount. Production code must consume canonical normalized source fields rather than make ad-hoc column guesses in the compiler.
- PDF remains important as fallback/stress path. PDF Reader fields such as generic `ui_amount` must not automatically be treated as authoritative journal amounts.

## What the deterministic/Python compiler should do
The compiler must be deliberately small. It should **not** understand products or choose accounting policy.

Inputs should already contain:
- authoritative document direction/mode from Planner: ordinary purchase, ordinary sale, purchase return, sales return (or equivalent explicit representation),
- counterparty account decision/match,
- authoritative normalized source amounts/taxes/payable,
- AI-selected chart account for each business row, with `needs_review`,
- exact chart membership metadata.

Compiler responsibilities:
- verify selected account exists and is a valid/detail account,
- place authoritative row amounts on the selected accounts,
- place source VAT/special-tax amounts on the selected tax accounts,
- mechanically apply debit/credit orientation from authoritative transaction mode,
- create/use the counterparty balancing line from Planner/counterparty matching,
- ensure all source rows remain traceable,
- preserve zero-value source rows without inventing revenue/expense,
- compute debit/credit totals and validate balance,
- surface unresolved differences/placeholders instead of inventing a semantic account,
- keep `needs_review` visible while still producing a draft journal whenever possible.

Compiler must NOT decide whether MOXI is a hearing aid, whether coffee is personnel food vs representation, whether SLIM TAPER is apparel, or whether QNB kontör is software/e-document vs communication. Those are AI/accountant-policy decisions.
## Rules / learning conclusion so far
- Do not make learned concepts or exact phrase matchers load-bearing. The system must work on the first invoices with zero accumulated memory.
- Existing learning/rule architecture is still useful as context/authority: accountant corrections, tenant rules, counterparty rules, service-profile rules, and exact verified overrides can improve future calls.
- Example: accountant correction `ARVELES -> medicine` may be a reusable semantic fact across dosage/pack variants, while the account code remains tenant/chart specific.
- Do not require 100k invoices before the system becomes useful.
- No real large corpus of accumulated production rules was found in the private pilot files, so a "many real rules" quality test has not yet been honestly completed. Do not fabricate hundreds of mock rules and call that validation.

## Exact next model experiment
Do not invent another architecture before completing this benchmark.

Target flow:
`eligible HTML -> deterministic HTML source package -> existing Planner -> ONE model account-selection call -> small compiler/validator`

The account-selection model receives:
- raw normalized invoice rows,
- Planner direction/counterparty context,
- client activity,
- the taxpayer's **full real detail chart** (no manually selected 30-account shortlist),
- instruction: choose the most plausible real account for every business row; if uncertain still choose best account and set `needs_review=true`; blank only if genuinely no plausible chart account.

Model order must be sequential to reduce XKIRO/rate interference:
1. Luna finishes the entire fixed HTML set.
2. wait ~15 seconds.
3. Kimi K2.6 finishes the same set.
4. wait ~15 seconds.
5. DeepSeek runs the same set. Prefer direct DeepSeek now that production/direct transport is known good; do not use the removed XKIRO DeepSeek alias.

Keep identical source package, Planner output, chart, schema, and compiler for all models. Record per invoice: selected account(s), review flags, latency, provider error separately from accounting error, source coverage, debit/credit balance, and obvious semantic/account mistakes. Do not change prompt midway unless the current run is first frozen as a result.
## Useful experiment files / references
- `tmp/probe_real_minimal_row_harness_20260917.py`: real PDF minimal Reader -> Luna semantic -> Luna account experiments.
- `tmp/real-minimal-row-harness-20260917.json`: corresponding early result set.
- `tmp/benchmark_html_split_3models_20260917.py`: HTML split benchmark across Luna/Kimi/DeepSeek; useful for source preparation and fixed cases, but it still uses two AI calls.
- `tmp/smoke_html_three_stage_deepseek_direct_20260917.py`: production-like HTML three-stage smoke using direct DeepSeek.
- `backend/tests/test_deepseek_final_provider.py`: transport contract for direct DeepSeek Final Accountant.
- `docs/rule-engine-and-learning.md`: current learning/rule architecture.
- `tmp/expert_trace_v1_20260917.md`: structured expert/accounting trace examples from Orhan invoices.

## Repo/deploy caution
- The primary local repo `C:\Users\kerem\Documents\Fisero` contains unrelated dirty work from other tasks. Do not stage/overwrite unrelated changes.
- The production hotfix was intentionally built in a clean worktree and pushed as exact deploy commit `22f3499`.
- Production deploy path is GitHub Actions -> AWS OIDC -> SSM exact SHA.
- Current production server was verified at `22f3499ffe47066537d182b90a8e2b3e94cb7c63` with healthy backend/frontend after the hotfix.
- Never print or copy API secret values into chat/logs.

## Separate UI end-to-end check to run in another chat
Goal: verify the **actual live user journey**, not another isolated model benchmark.

Use the production UI as an accountant/user would:
- sign in through the UI,
- select a known taxpayer with chart loaded,
- upload a fresh real HTML invoice if possible (happy path); optionally repeat with PDF afterward,
- confirm upload starts automatically where expected,
- watch document progress from upload/source-read through Planner and Final Accountant,
- confirm the document reaches the workbench/review result rather than silently stopping,
- inspect source rows, selected accounts, VAT/taxes, counterparty, balance, review flags, and final status,
- verify no XKIRO DeepSeek 404 remains in logs because Final Accountant should now use direct DeepSeek,
- if it fails, trace the exact stage and error before changing code.

Do not modify architecture during this E2E check. First establish whether the current deployed production path works from UI upload all the way to an accounting result.
