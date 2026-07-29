---
name: fisero-review-accounting
description: Review a Fisero accounting flow or change for canonical evidence, invoice direction, line meaning, VAT, chart-account context, balanced journal construction, explainability, learning scope, review state, and export safety. Use for invoice automation, journal drafts, account selection, KDV, returns, accountant corrections, learning rules, onboarding readiness, or any claim that an accounting result is correct.
---

# Review Fisero Accounting

## Start from evidence

Read the relevant canonical product decision and trace the actual data path.
Prefer original XML/PDF evidence, canonical parsed fields, real chart-plan data,
and accountant decisions over normalized summaries or plausible inference.

If invoice lines are absent, do not infer product or service meaning from the
seller name. Mark the result `line-missing` or `insufficient-evidence`.

## Review in order

1. Confirm document identity, parties, direction, dates, currency, totals, and
   source provenance.
2. Confirm canonical line items and VAT summary reconcile with totals.
3. Separate deterministic legal, balance, VAT, direction, and export guards
   from semantic AI judgment.
4. Check account candidates against the real, direction-filtered client chart
   plan and counterparty context.
5. Check the journal is balanced and every amount has an explainable source.
6. Check uncertainty produces a useful draft and an actionable review reason;
   `review_required` alone is not success.
7. Check accountant correction and learning scope are explicit, conflict-safe,
   authorized, and never silently overwrite protected work.
8. Check export readiness independently from processing completion.

## Ground and report

Use the relevant canonical Fisero accounting and product decisions as the
authority. Do not introduce a simulated accountant persona or reopen settled
decisions. When the canonical documents do not settle a material accounting
question, identify the exact gap and leave it for the user, real pilot
accountant, or verified official guidance rather than filling it with generic
advice.

Report:

- what the system understood;
- evidence used and missing;
- proposed accounting result;
- deterministic and AI reasoning;
- risks or blocking gaps;
- accountant action, if any;
- tests and real-accountant validation still required.

Read [references/evidence-checklist.md](references/evidence-checklist.md) for the
minimum proof contract.
