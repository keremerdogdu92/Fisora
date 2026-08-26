# Fisora Next Execution Backlog — 2026-08-25

## Current Baseline — updated 2026-08-26

- Authoritative branch remains `main` only.
- Local and production were verified at `70601f7` before the current password-reset/Brevo patch; the current patch is still uncommitted and undeployed.
- Real-data pilot gate is OPEN in production: `real_data_pilot.allowed=true`.
- Authoritative accounting remains intentionally disabled; pilot output is not an official accounting record.
- Admin visibility is wildcard client access so the admin account can see current and future taxpayers.
- Arif San is present in production with tax certificate, chart of accounts and five selected real invoices. Three invoices already existed; the two missing sales invoices were uploaded through the real HTTP endpoint and both processing jobs reached `completed`.
- Full backend regression for the password-reset/Brevo patch: **1106 passed, 34 skipped, 0 failed**.
- Frontend regression: **176 passed**; production build succeeds and `/portal/password-reset` is present.
- A valid Brevo transactional-email credential was recovered from the Medikal-Production Antigravity workspace and verified against Brevo with HTTP 200. The secret has not yet been copied into Fisora production env.
- Password-reset/Brevo changes still require final review, commit, push, production secret wiring, deploy and live end-to-end reset-mail verification.

## Status Matrix

| Item | Status | Immediate dependency / next action |
| --- | --- | --- |
| 0. Password reset / production login | IMPLEMENTED / NOT DEPLOYED | Final diff/security review -> commit/push -> copy Brevo secret to production env -> deploy -> live reset email -> normal admin login. |
| 1. Real production accountant flow | PARTIAL FIELD PROOF | Gate is open and five real invoices are present. Complete source-vs-Reader/Planner/Final audit and persistence/re-login proof using the normal admin account. |
| 2. Progressive UI production validation | DEPLOYED / FIELD PROOF MISSING | Measure real Reader visibility latency, Planner/Final transitions and refresh behavior on the same real documents. |
| 3. Tax-certificate field validation | LIVE / FIELD PROOF MISSING | Arif tax certificate is stored; compare extracted identity/NACE/date fields directly with the source document. |
| 4. Counterparty workflow | PARTIAL | Existing Planner exact/none/uncertain contract remains; safe creation/approval/update lifecycle is still open. |
| 5. Final Accountant provider decision | PRODUCTION ACTIVE / COMPARISON PAUSED | Xkiro DeepSeek V4 remains production Final; direct DeepSeek comparison can wait until the field audit is stable. |
| 6. Reader/UI quality audit | FRESH RUN NEEDED | After closing items 0-3, run 20 -> 50 -> 100 source-fidelity audit. |
| 7. HTML invoice reader | NOT IN MAIN / ISOLATED WORKSTREAM | Continue isolated HTML corpus/parser work before integration. |
| 8. Research agent | INFRA PRESENT / THREE-STAGE INTEGRATION MISSING | Current three-stage pipeline still has no research call. |
| 9. Accountant copilot / Hermes | LEARNING CORE PRESENT / COPILOT MISSING | Learning core exists; conversational/statistics/reporting copilot layer remains open. |

## P0 — Start Real Accountant Usage

### 1. Real production accountant flow

Goal: validate the complete accountant-facing production flow with one taxpayer and five real invoices.

Execution flow:
1. Confirm `real_data_pilot.allowed=true` before uploading accountant-owned documents.
2. Log in with a real accountant session.
3. Create or select one taxpayer.
4. Upload the taxpayer's tax certificate.
5. Import the real chart of accounts.
6. Upload five real PDF invoices.
7. Confirm Reader/source rows appear before Final completion.
8. Confirm Planner accounting intent and Final journal draft.
9. Confirm document/result persistence after refresh/re-login.
10. Record defects with document ID, stage, evidence, and expected behavior.

Field evidence status — 2026-08-26:
- Pilot gate: COMPLETE (`real_data_pilot.allowed=true`).
- Existing taxpayer: COMPLETE (`Arif San`).
- Tax certificate: STORED / source-field audit still required.
- Chart of accounts: STORED.
- Five selected real invoices: PRESENT. Three already existed; two missing sales invoices were uploaded via the real production HTTP endpoint and reached `completed`.
- Progressive Reader-before-Final proof: OPEN.
- Planner/Final source-vs-PDF accounting audit: OPEN.
- Refresh/re-login persistence using the user's normal password-backed admin session: OPEN, blocked only by password-reset production release.
- No `completed` processing status is accepted as accounting-correctness evidence by itself.

Acceptance:
- Tax certificate identity/NACE is correct or safely `partial`; no wrong profile mutation.
- Five invoices persist source rows and journal drafts without blank-screen waiting.
- Payable, VAT, line count, direction, and journal balance are inspected against the PDF.
- No mock/synthetic success is counted as evidence for this item.

Pilot policy decided on 2026-08-25:
- Real historical invoices, tax certificates and charts may be used for repeated non-authoritative testing.
- Losing pilot source copies is acceptable because source documents remain available outside Fisora and can be reprocessed.
- Do not tag or split document records into artificial pilot/production datasets.
- Test-period outputs and Zirve/Luca transfer experiments are allowed while they are not treated as official books/records.
- The critical transition is explicit: Fisora output becomes authoritative only when the accountant starts using active-period output as an official accounting record.
- Pilot backup priority is accountant learning/review decisions, not replaceable source PDFs.

Real-data pilot requirements:
- explicit pilot enable,
- restricted TLS/network access,
- session-backed authentication,
- PostgreSQL/storage/rate-limit/provider readiness.

Authoritative accounting requirements are separate and remain disabled by default:
- explicit `FISORA_AUTHORITATIVE_ACCOUNTING_ENABLED=true`,
- real-data pilot already allowed,
- scheduled backup mode,
- fresh recoverable backup/restore proof.

### 2. Progressive UI production validation

Run the same five-document set and measure:
- Reader result visibility latency.
- Planner and Final stage transitions.
- Selected-document polling/refresh behavior.
- Source-row preservation on Final failure/retry.
- Stage/error labels visible to the accountant.

Acceptance: the accountant sees useful invoice content while downstream stages are still running; Final failure never erases Reader evidence.

### 3. Tax-certificate field validation

Use representative text PDF, scanned PDF, image, TCKN-only and VKN cases.

Acceptance:
- TCKN/VKN checksum validation prevents bad identity writes.
- `title`, `tax_identifier`, and six-digit NACE satisfy the parsed gate.
- Weak documents remain `partial`; profile update is blocked.
- AI vision failure safely falls through to OCR.

## P1 — Accounting Quality and Counterparty Safety

### 4. Counterparty workflow

Define and validate:
- Existing counterparty matching by VKN/TCKN.
- New counterparty suggestion without auto-creating an unsafe ledger identity.
- Accountant approval/correction path.
- No mutation of an existing counterparty from weak name-only evidence.
- New taxpayer strategy where future counterparties are created with tax identity evidence.

Keep this isolated from Final Accountant account-selection authority.

### 5. Final Accountant provider decision

Current reference leader: Xkiro DeepSeek V4 stored TTNet baseline.
Remaining serious experiment: DeepSeek direct API.

Evaluation order:
1. TTNet purchase.
2. Yurtiçi purchase.
3. Erkan sale.
4. 10–20 real invoices only if the candidate survives the first three.

Priority: economic validity → expected account semantics → Planner contract preservation → chart-valid codes → balance → latency/cost.

## P2 — Corpus and Source Coverage

### 6. Reader/UI quality audit

Run a staged source-fidelity audit: 20 → 50 → 100 documents.

Compare PDF evidence directly against Reader/UI output for:
- line count and duplicate/missing rows,
- description,
- quantity/unit,
- unit price,
- taxable amount/VAT,
- gross/payable totals,
- invoice direction and parties.

Do not score accounting semantics in this audit. Reader fidelity is the acceptance target.

### 7. HTML invoice reader

Keep the HTML work isolated from the PDF pipeline until the extraction contract is stable.

Goal: extract invoice header, parties, totals and source rows without assigning accounting meaning.
Use the large collected HTML corpus to measure template coverage and fallback behavior before integration.

## P3 — Agent Capabilities

### 8. Research agent

Allow Planner/Final to request external product/service research only when meaning is genuinely uncertain.

Requirements:
- research is evidence, not a second accounting authority,
- batch related product questions when useful,
- preserve source URLs/evidence and query reason,
- do not impose an arbitrary low question count that hides uncertainty,
- verify important claims against primary/official sources when possible.

### 9. Accountant copilot / Hermes layer

Build above the invoice pipeline rather than inside Reader.

Target capabilities:
- cross-client tax/VAT anomaly questions,
- period comparisons and operational statistics,
- controlled Excel/report generation,
- regulation/evidence lookup,
- explanation of prior accounting decisions,
- persistent learning from explicit accountant corrections and confirmed rules.

This layer must not silently rewrite source evidence or bypass review/audit controls.

## Recommended Execution Order — updated 2026-08-26

1. Finish password reset/Brevo production release and verify normal admin login with a real reset email.
2. Use the normal admin account to audit Arif San: tax certificate + chart + five real invoices.
3. Verify Reader -> Planner -> Final progressive behavior, refresh/re-login persistence, and source-vs-output correctness.
4. Repair any defects found by that field run; close items 1-3 only with fresh runtime/source evidence.
5. Resolve safe counterparty creation/approval/update lifecycle.
6. Expand the Reader/UI source-fidelity audit to 20 -> 50 -> 100 documents.
7. Revisit Final provider comparison only after the field audit is stable.
8. Continue HTML reader, Research Agent, and Hermes as separate workstreams.

## Evidence Rule

Every item is closed only by fresh runtime evidence. Tests, mocks, synthetic fixtures, or balanced journals alone do not prove real-document/accounting correctness when the acceptance criterion requires source inspection or accountant review.
