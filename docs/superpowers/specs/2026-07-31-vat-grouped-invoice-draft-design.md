# VAT-grouped Invoice Draft Design

## Status and decision

Status: Accepted for implementation planning.

Fisero will use UBL/XML as the normal canonical invoice source. Text-readable
PDF remains a supported but uncommon fallback for manually supplied invoices.
Image-only/scanned PDF OCR is outside this pilot slice.

Within one invoice, canonical lines that share the same source VAT identity
default to one semantic net-account decision. Model uncertainty or wording
variation alone does not split the group. A group is split only by a
client/accountant-confirmed exception; AI may show a first-seen possible
exception for focused review but does not silently fragment the default group.
Every canonical line remains individually traceable even when the journal
presentation aggregates the group.

## Direction contract

Ordinary invoice intake always supplies `purchase_invoice` or `sales_invoice`.
There is no normal `unknown` invoice-direction state.

- QNB incoming acquisition supplies `purchase_invoice`.
- QNB outgoing creation remains a separate sales flow.
- Manual portal intake supplies the selected purchase or sales lane.
- Private/corpus manifest import requires an explicit direction per invoice.
- Exact UBL supplier/customer VKN matching against the current client validates
  direction and wins over a conflicting intake label.
- A direction conflict is visible review evidence; it does not force the wrong
  intake direction or erase the draft.
- Return behavior is represented separately from base purchase/sales direction.

The current corpus will be reimported after a preflight proves exactly 35
purchase and 15 sales sources and validates every available XML party identity.

## Canonical VAT identity

The VAT grouping key is not only the percentage. It is:

```text
tax scheme + tax category + rate + exemption reason code
```

Canonical line and VAT-summary records retain:

- tax scheme/type code;
- tax category code;
- VAT rate;
- exemption reason code when present;
- stable `vat_group_id`;
- source position/evidence;
- contributing canonical line IDs.

This distinction matters especially for zero-rate/exemption behavior. Two lines
with the same percentage but different source tax treatment are not the same
VAT group.

## Supported-source extraction contract

### UBL/XML

Every material invoice line is read directly from the structured source. Each
declared `TaxSubtotal` is reconciled against the lines with the same VAT
identity. A missing group-line relationship is a canonical parser defect, not
an acceptable review shortcut.

### Text-readable PDF

The parser preserves text and source positions, extracts summary fields and
table rows separately, normalizes Turkish monetary formats, and reconciles
lines against VAT groups and document totals.

If a declared VAT group has no explainable line:

1. run targeted deterministic table/row recovery for that exact rate and
   amount gap;
2. run source-grounded AI discovery limited to the missing group;
3. require non-empty, unique page/row source positions;
4. rerun deterministic VAT and total reconciliation.

A supported text PDF is not considered successfully processed while any VAT
group lacks at least one explainable canonical line. Persistent absence is a
technical extraction failure with `line-missing`; it is not converted into a
seller-name-only accounting decision or an empty review result. The protected
corpus acceptance target is zero such failures.

## Group-account algorithm

Grouping is scoped to one invoice. Fisero never combines every `%20` line across
different invoices.

For each canonical VAT group:

1. provide all group line descriptions and IDs, client activity, counterparty,
   direction, the full searchable direction-filtered chart, and applicable
   confirmed rules;
2. select one real `group_account` for the group's net amount;
3. materialize one decision per contributing canonical line with
   `decision_origin=vat_group_default`;
4. preserve a confirmed line-level exception when its exact trigger matches;
5. present a first-seen possible exception to the accountant without letting
   mere uncertainty silently fragment the group;
6. aggregate journal presentation only where account, direction, and source tax
   identity match.

For purchases, the semantic group account is the appropriate real net-side
account such as stock, expense, or fixed asset (`153`, `7xx`, `25x` families as
available in the real chart). For sales, it is the appropriate real revenue
account (`600` family and its real details). Source VAT facts separately bind
the VAT side to the usable direction/rate account (`191` for purchase, `391`
for sales). Counterparty resolution separately binds `320` for purchase or
`120` for sales.

Example: a hearing-business purchase invoice has battery, accessory, and mould
lines, all in the same `%20` source VAT group. The default output is one net
group account such as the real `153.01.002`, one `%20` deductible-VAT line such
as `191.01.020`, and the supplier `320` line. It does not request three
independent semantic decisions merely because the descriptions differ.

## Journal construction and review

The journal builder consumes canonical VAT groups and their group-account
decisions:

- net amount goes to the selected group account;
- source VAT amount goes to the usable `191` or `391` account;
- payable/receivable goes to the resolved or proposed `320`/`120` account;
- zero-tax groups do not invent a VAT journal line;
- each journal row retains VAT-group ID, contributing canonical line IDs, and
  allocated amounts.

Known rows are never discarded because a different component needs focused
review. An unresolved source contradiction produces the accepted
`Belge toplam farki - kontrol` candidate with source values and rationale, not
an empty journal or a generic suspense account.

Cancelled or fully allowed zero-payable documents produce an explained
`no_posting_suggested` result. During the pilot an accountant confirms the
reason.

## Preview and accountant workflow

UBL is rendered locally as an invoice-like preview. PDF remains the original
document preview. Both use the same adjacent accounting-draft surface.

The invoice preview shows, in order:

1. source invoice lines with a textual VAT-group badge;
2. an always-visible compact `KDV dagilimi` table;
3. existing document totals.

Each VAT-group row shows:

- group label, including exemption code when present;
- taxable base;
- VAT amount;
- group gross total;
- contributing source line numbers.

Source-line VAT badges link to the group summary; group source-line links return
to the corresponding rows. The relationship is not communicated by color
alone. Canonical IDs, UBL source paths, and detailed reconciliation remain
progressive technical detail.

The adjacent draft row shows the source VAT group and contributing invoice
lines. Selecting the row makes its source relationship inspectable. `KDV
grubu` is never labelled as `hesap grubu`; the accounting decision is shown
separately.

## Learning scope

An unchanged accountant approval confirms the current draft. A reusable
VAT-group account rule is proposed only through the existing explicit learning
confirmation. A confirmed line exception records its positive trigger and
scope. Model uncertainty, description variation, or one arithmetic defect does
not become a reusable exception rule.

## Acceptance

- Every ordinary intake invoice has purchase or sales direction.
- The corrected corpus preflight proves 35 purchase and 15 sales sources.
- Every UBL and supported text PDF has at least one canonical line per declared
  VAT group.
- Every canonical line has exactly one semantic account decision and journal
  allocation.
- Same-group lines default to one group account.
- Uncertainty alone does not split a group.
- Every preview shows per-group taxable base, VAT, gross, and source lines.
- Every draft row is traceable back to source VAT groups and canonical lines.
- The 50-document run produces 44 populated/editable drafts, six explained
  no-posting suggestions, and zero false parse/persistence failures.
- Accountant reference outcomes remain the quality authority.

## Non-scope

- Image-only/scanned invoice OCR.
- Routine XML/PDF pair fetching or comparison.
- Direct Zirve transmission.
- Generic whole-invoice or seller-name-only account fallbacks.
- Automatic learning without accountant confirmation.
- Commit, push, deploy, or production reprocessing as part of documentation.
