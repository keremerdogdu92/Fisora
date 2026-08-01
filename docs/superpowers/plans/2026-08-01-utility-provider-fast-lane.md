# Utility Provider Fast Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` task by task. Do not create a generic expense fallback.

**Goal:** Let common UBL electricity, gas, GSM, and fixed-internet invoices select an accountant-useful tenant account quickly; the accountant normally approves rather than chooses.

**Architecture:** A versioned global ProviderDirectory maps an UBL supplier VKN to a small service profile. That profile enriches the existing canonical UBL/account-selection flow; it never supplies a global ledger account. AI selects one real account from the tenant's direction-filtered chart, and an approval persists a tenant-scoped profile rule for future invoices. PDF remains a limited title/VKN adapter.

**Scope:** `gsm_communication`, `fixed_internet`, `electricity`, `water`, `natural_gas`; the initial catalog covers the 21 incumbent electricity retail companies, major city-gas distributors, and common GSM/fixed-internet invoice issuers. A directory record is directly usable: UBL resolves it by issuer VKN; PDF resolves it only by an exact normalized legal-title or listed brand-title alias. The catalog never holds a global ledger account. UBL device/taksit markers require one focused first review, then an approved tenant/provider marker rule suppresses repeat review. No new PDF OCR or PDF installment handling.

## Tasks

1. Add test-first ProviderDirectory data, duplicate validation, VKN/title match result, and direct-use national seed records for common GSM, fixed-internet, electricity and natural-gas issuers.
2. Enrich canonical UBL processing with profile evidence and exact supplier-VKN resolution; UBL VKN remains required for the fast lane.
3. Add profile-aware account selection: AI receives profile + real tenant account candidates, returns a real account, and never falls back to a generic expense account.
4. Persist approved tenant `service_profile -> account` rules, with a provider-specific override for a corrected exception.
5. Add UBL-only device/taksit marker detection and first-review/approved-repeat behavior; do not block ordinary service lines.
6. Map profile reason, selected account, and correction action to the existing accountant review UI.
7. Add focused unit/UBL/PDF/UI tests, then run the existing full backend/frontend/build/diff proof before deciding on the already-planned pilot corpus and release Tasks 7-8.

## Acceptance

- Vodafone/TTNET/Enerjisa/IGDAS UBL invoice maps to its profile by supplier VKN.
- First invoice: AI picks a real tenant detail account; accountant sees `Onayla ve geç` and may correct.
- Approved profile rule skips repeated account-selection review for the same tenant/profile/direction.
- A provider-specific correction wins over the general profile rule.
- TTNET marker invoice needs focused first review; same approved marker repeats without review.
- No profile can select an account outside the tenant chart, reverse direction, invent VAT, or silently use a generic expense fallback.
- PDF only uses VKN/title profile enrichment; unsupported PDF detail goes to existing AI/review behavior.
