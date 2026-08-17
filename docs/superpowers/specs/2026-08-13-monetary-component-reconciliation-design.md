# Monetary Component Reconciliation Design

Status: Approved

## Goal

Add a general monetary-topology layer between canonical invoice extraction and
account selection. The layer must reconcile lines, VAT, special taxes, fees,
discounts, carryovers, withholding, rounding, device/installment charges, and
other monetary components against the document's named totals without turning
uncertainty into a blank or unusable journal draft.

The design is source-format neutral. PDF, HTML, and UBL may produce the same
canonical facts; reconciliation and journal construction do not depend on the
source format.

## Approved boundaries

- Gemini extraction reports visible document facts: labels, codes, rates,
  bases, amounts, source positions, evidence, and explicitly printed totals.
- Extraction does not select accounts and does not decide whether a component
  belongs to an ambiguous generic "tax total".
- The reconciliation layer derives the best-fitting relationship between facts
  and named totals using arithmetic plus document semantics.
- The accounting AI still selects only real, active, sent tenant candidates.
  Reconciliation never selects an account.
- Warnings remain visible but do not erase or suppress a useful draft.
- Accountant approval remains the export authority.
- The current document-processing UI is not expanded.
- No parser or Textract fallback is introduced.

## Problem being removed

The current extraction schema asks Gemini for `included_in_tax_total`, although
"tax total" may mean VAT total, special-tax total, tax-inclusive total, or a
payable total. Repeated extraction can therefore return defensible but different
yes/no answers for the same physical component.

The journal builder then treats any unknown inclusion value as an unknown
posting side. A tax with a known amount and known payable-increasing effect can
therefore disappear from posting solely because its membership in an unrelated
subtotal is unknown. Component IDs also include these derived values, so the
same source fact may receive a different identity after reprocessing.

## Canonical extraction contract

New native-PDF extraction responses contain no component-membership booleans.

Tax components retain:

- `component_type`
- `source_label`
- `source_code`
- `rate`
- `taxable_amount`
- `tax_amount`
- `source_position`
- `evidence`

Monetary components retain:

- `source_label`
- `source_amount`
- `source_position`
- `evidence`

The canonical mapper continues accepting legacy `included_in_*` fields so old
artifacts and test fixtures remain readable. Legacy values are hints, not
posting authority.

## Stable fact identity

Tax component identity uses only stable observed source facts:

```text
source + source_position + source_code + source_label + rate + base + amount
```

Monetary component identity uses:

```text
source + source_position + source_label + amount
```

Occurrence index distinguishes two truly identical visible facts. Provider
classification, normalized kind, economic effect, and total-membership answers
must not change the identity.

## Reconciliation model

`reconcile_monetary_projection(projection)` is a pure domain operation. It
receives the compact fact projection and returns the same projection enriched
with component topology and a document reconciliation summary.

Each tax and monetary component receives:

- `total_memberships`: state for `line_net_total`, `line_gross_total`,
  `vat_total`, `special_tax_total`, `tax_inclusive_total`, and `payable_total`;
- `total_membership_basis`: `arithmetic_exact`, `arithmetic_best_fit`,
  `semantic`, `provider_hint`, `not_applicable`, or `unresolved`;
- `payable_membership`: compact payable state for downstream transport;
- `posting_requirement`: `separate`, `represented`, `excluded`, or
  `unresolved`;
- component-local warnings.

The document summary contains:

- `status`: `exact`, `partial`, or `not_testable`;
- observed payable total;
- mandatory line-plus-VAT total;
- selected component effect total;
- reconciled payable total;
- signed residual;
- selected and excluded component refs;
- warnings.

## Arithmetic selection

Line taxable amounts and canonical VAT-summary amounts form the mandatory
posting base. VAT tax components already represented by VAT summaries are not
counted twice.

Every remaining component contributes a signed candidate amount:

- VAT/special/other tax and charges increase payable;
- withholding, discounts, negative adjustments, and next-period carryovers
  decrease payable;
- a source sign overrides a generic positive-charge default where applicable.

When a payable total exists, a bounded deterministic subset solver chooses the
component combination with the smallest residual. Exact arithmetic outranks
legacy provider hints; hints break otherwise equal choices. The state space is
bounded so a malformed document cannot cause exponential resource use. If no
exact topology exists, the closest useful topology is retained and its residual
becomes a warning.

When no payable total exists, known economic effects are still postable.
Provider hints and semantic defaults choose a useful topology, while the
summary is `not_testable` rather than blocking the draft.

Named subtotal memberships use the same arithmetic mechanism with the relevant
baseline and candidate set. Unknown membership in one subtotal never makes a
known payable posting side unknown.

## Journal and accounting-decision behavior

- `separate`: request/select an account and post using the known economic
  effect.
- `represented`: retain a zero-posting representation line because another
  canonical fact already carries the amount.
- `excluded`: retain a zero-posting representation line because the best
  topology does not include the component in current payable.
- `unresolved`: retain an unresolved line only when amount/economic effect is
  actually unusable, not merely because a subtotal membership is unknown.

`required_decision_refs_for_projection` asks the accounting AI only for
`separate` or genuinely `unresolved` facts. Represented/excluded facts remain in
the projection and audit trail without consuming decision capacity.

## Telecom acceptance example

The design must reconcile this equation exactly:

```text
14.04 service lines
+ 2.81 VAT
+ 1.40 special communication tax
+ 26.98 radio usage fee
+ 0.17 prior-period carry
- 0.15 next-period carry
= 45.25 payable
```

The OIV and radio fee must post even if a legacy provider returned
`included_in_tax_total=unknown`. OIV membership in a printed 1.40 special-tax
total and both components' membership in the 45.25 payable total are separate
facts.

## Non-scope

- Account creation or automatic counterparty creation.
- Export approval or legal-compliance authorization.
- UI redesign.
- Silent extraction fallback.
- A second paid Gemini repair call. The reconciliation summary exposes an exact
  residual and involved refs so a later targeted repair stage can request only
  missing monetary evidence without changing this domain contract.

## Acceptance criteria

1. The telecom example produces an exact reconciliation and balanced journal.
2. Unknown `included_in_tax_total` cannot suppress a known tax posting.
3. Changing only derived inclusion/effect fields cannot change component IDs.
4. New extraction schemas no longer ask Gemini for ambiguous membership
   booleans, while legacy payloads remain readable.
5. Duplicate VAT facts remain represented once.
6. Partial reconciliation preserves the closest useful draft and emits a
   residual warning.
7. Existing V2 capacity, tenant-candidate validation, chunking, artifact
   lineage, worker flag, and UI behavior remain unchanged.
