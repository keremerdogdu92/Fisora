# Fisora Next Execution Backlog — 2026-08-25

## Current Baseline

- Authoritative branch: `main` only.
- Local, `origin/main`, and production checkout: `1647df5`.
- Production smoke: `status=ok`, `completed_jobs=1`, `SMOKE_EXIT=0`.
- Production HTTP: `/health=200`, root `200`, readiness `ready=true`, `pilot_sellable=true`.
- Full local release gate: 1136 backend tests passed, 34 skipped, frontend tests passed, production build passed.
- Current production env still has `FISORA_REAL_DATA_PILOT_ENABLED=false`; code now treats real-data testing and authoritative accounting as separate readiness levels.

## Status Matrix

| Item | Status | Immediate dependency / next action |
| --- | --- | --- |
| 1. Real production accountant flow | READY AFTER PATCH DEPLOY / ENV ENABLE | Real historical documents may be used for non-authoritative testing without production backup. Keep authoritative accounting disabled. |
| 2. Progressive UI production validation | DEPLOYED / FIELD PROOF AFTER #1 | Stage snapshots, persistence, polling and UI mapping are in `main`; validate latency/UX with the same five real documents. |
| 3. Tax-certificate field validation | LIVE / NEEDS FIELD PROOF | AI-assisted reader is deployed; validate representative real text/scanned/image cases after the gate opens. |
| 4. Counterparty workflow | PARTIAL | Three-stage Planner resolves supplied candidates as exact/none/uncertain and emits `new_counterparty_required`; safe creation/approval/update lifecycle is still open. |
| 5. Final Accountant provider decision | PRODUCTION ACTIVE / COMPARISON PAUSED | Production Reader+Planner use Gemini 3.5 Flash Lite and Final uses Xkiro DeepSeek V4 Flash; DeepSeek direct remains the last serious comparison. |
| 6. Reader/UI quality audit | AUDIT ASSETS PRESENT / FRESH RUN NEEDED | Existing 12/50-document audit assets are local evidence; run a fresh post-release 20 -> 50 -> 100 source-fidelity audit. |
| 7. HTML invoice reader | NOT IN MAIN / ISOLATED WORKSTREAM | Main has HTML preview rendering only, not an HTML invoice extraction engine; continue the isolated corpus/parser work before integration. |
| 8. Research agent | INFRA PRESENT / THREE-STAGE INTEGRATION MISSING | Research harness/evidence paths exist in the legacy processing stack, but the current three-stage pipeline has no research call. |
| 9. Accountant copilot / Hermes | LEARNING CORE PRESENT / COPILOT MISSING | Versioned learning-rule services and application exist; no Hermes-style conversational/statistics/reporting copilot layer exists yet. |

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

## Recommended Execution Order

1. Open the real-data pilot gate safely.
2. Run one taxpayer + tax certificate + chart + five real invoices in production.
3. Repair progressive UI defects found by that run.
4. Expand to 20 real invoices.
5. Resolve counterparty workflow.
6. Close Final provider decision with DeepSeek direct vs Xkiro.
7. Expand Reader/UI audit to 50–100 documents.
8. Continue HTML reader, Research Agent, and Hermes as separate workstreams.

## Evidence Rule

Every item is closed only by fresh runtime evidence. Tests, mocks, synthetic fixtures, or balanced journals alone do not prove real-document/accounting correctness when the acceptance criterion requires source inspection or accountant review.
