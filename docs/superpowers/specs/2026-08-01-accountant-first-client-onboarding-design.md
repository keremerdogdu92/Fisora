# Accountant-first client onboarding

## Decision

An accountant can create an accounting-ready client without creating a client portal password. Portal access is optional and created later with the existing invite flow; the client sets their own password after accepting the invitation.

## Behaviour

- Required onboarding inputs: canonical identity/activity evidence and a parsed chart plan.
- `portal_users` may be empty. The signed-in accountant still receives access to the new client.
- Portal invitation is post-create and optional; it never stores a generated client password.
- Accounting readiness stays based on identity, activity/address, and chart accounts, not portal access.
- Tests use generic client fixtures. Rana and its 916 accounts are live acceptance data, not a coded rule.

## Acceptance

With password bootstrap disabled, a signed-in accountant creates a client, selects it, and uploads invoices. A later invitation succeeds independently and does not expose a password.
