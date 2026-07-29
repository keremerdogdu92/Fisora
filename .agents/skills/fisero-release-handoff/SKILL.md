---
name: fisero-release-handoff
description: Prepare and execute a verified Fisero release transaction covering intentional staging, commit, push, production deploy, parity checks, smoke, and handoff continuity. Use only when the user asks to commit, push, publish, deploy, sync local/GitHub/server, verify whether production is current, or update the release handoff; do not use for ordinary local implementation or local-only verification.
---

# Release and Hand Off Fisero

## Establish the requested transaction

Separate status inspection from mutation. If the user only asks whether GitHub
or production is current, inspect and report without requesting or performing a
release.

For a requested release, identify:

- intended files and excluded dirty-worktree changes;
- source and target branch;
- remote and production target;
- required tests, build, migrations, and smoke;
- whether `docs/current-handoff.md` must change;
- any release bookkeeping commit needed after runtime verification.

Read `docs/current-handoff.md` for continuity, but verify every drift-prone fact
against Git, the release script, and the live target.

## Complete read-only preflight

Before asking for release approval:

1. Inspect branch, HEAD, status, staged state, and ahead/behind counts.
2. Preserve unrelated user changes and generated artifacts.
3. Review the intended diff for secrets, private documents, migration risk, and
   accidental broad staging.
4. Run verification proportional to the change. Use the full proof set for a
   broad release unless the same checks already passed in this turn.
5. Use `deploy/scripts/fisora-release.ps1 -PlanOnly -Json` when a dry run adds
   useful target/parity evidence.
6. Resolve ordinary local failures before presenting the release gate.

Do not commit, push, deploy, rewrite history, or change the server during
preflight.

## Ask once at the release boundary

Present one compact release proposal containing:

- exact file scope;
- commit intent/message;
- branch and remote;
- production target;
- completed verification;
- migration or operational risk;
- expected handoff bookkeeping.

Then ask one explicit question equivalent to:

> Commit + push + deploy aşamasına geçeyim mi?

A clear approval covers the exact proposed release transaction: intentional
staging, commit, push, deploy, live verification, and any already-disclosed
handoff/parity bookkeeping. Do not ask again between these steps.

Invalidate the approval and stop for a new decision when:

- file scope, branch, remote, or production target changes;
- a test/build/check fails after the gate;
- a conflict or non-fast-forward condition appears;
- a new destructive migration, data-loss, secret, or security risk appears;
- completing the release would require force-push, history rewriting, or an
  undisclosed extra action.

## Execute the approved transaction

1. Stage only explicit paths and recheck the staged diff.
2. Commit with an intentional message and record the commit.
3. Push normally; do not force-push.
4. Deploy with `deploy/scripts/fisora-release.ps1`, preferring its compact JSON
   summary. Use `-SkipLocalVerify` only when the required proof already passed
   in this turn.
5. Verify local, remote, and server branch/commit truth.
6. Verify health, readiness, smoke, and affected routes or workflows.
7. If the disclosed transaction requires a handoff-only follow-up commit,
   update and publish it, sync server parity when appropriate, and report both
   the runtime commit and final parity commit.

Stop on failure. Do not hide partial completion or automatically repair history.

## Report exact outcome

Report separately:

- local branch and commit;
- remote branch and commit;
- server branch and commit;
- tests/build/checks;
- deploy/smoke/readiness;
- runtime commit versus final parity commit, if different;
- excluded local changes;
- any incomplete or externally blocked proof.

Read [references/release-proof.md](references/release-proof.md) for the stable
command set, evidence levels, wrapper flags, and common failure handling.
