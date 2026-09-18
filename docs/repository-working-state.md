# Repository working-state policy

Updated: 2026-09-19

## Canonical source of truth

- `origin/main` is the canonical code line for normal development.
- Office and home working copies should normally finish a task with local `main == origin/main` and a clean `git status`.
- Production deployment state is separate from repository sync. A clean/synced repository does not by itself prove that the latest main commit is deployed.

## Learned-rule audit / Rule Harness

Canonical runtime:
- `backend/app/services/learned_rule_audit_shadow.py`
- integration points in `backend/app/workflows/document_processing.py`
- tests in `backend/tests/test_learned_rule_audit_shadow.py`

Reference design material:
- `docs/learned-rule-audit/SKILL.md`
- `docs/learned-rule-audit/integration-notes.md`
- `docs/current-handoff-2026-09-18-rule-harness-experiments.md`

The production model does not load `SKILL.md` by file name. The production three-stage audit procedure is encoded in the runtime service prompts and host orchestration. The skill files are design/reference material.

## Local lab artifacts

The repository-level `tmp/` directory is intentionally ignored.

Use it for:
- benchmark runners,
- benchmark JSON results,
- one-off UI automation scripts,
- temporary diagnostics,
- WSL/build helper scripts,
- scratch exports.

Files under `tmp/` are not source of truth and must not be required for production runtime. If a lab result becomes a product requirement or an architectural decision, move the durable conclusion into tracked code/tests/docs before relying on it.

## Archived pre-sync office state

Safety snapshot:
- branch: `archive/office-dirty-20260919`
- purpose: preserve the complete office dirty state before the 2026-09-19 reconciliation.

That branch includes historical/experimental material such as:
- the older v3 learned-rule audit service copy,
- xKiro plan-fallback experiment files,
- intermediate provider/env changes,
- pre-reconciliation rule-learning work.

Do not merge the archive branch wholesale into main. Recover individual files/hunks only after comparing them with current main.

## Local-only experiments

Experimental provider or quota-fallback code that is not deliberately promoted to main belongs either:
1. under ignored `tmp/`, when it is disposable/reproducible, or
2. on a named archive/experiment branch, when it must be preserved.

Do not leave production-path Python/TypeScript files untracked in the main working copy.

## End-of-task hygiene

Before considering a repository task complete:

1. `git fetch origin main`
2. confirm intended branch and HEAD
3. `git status --short` must be empty unless the remaining files are explicitly intentional
4. compare `git rev-parse HEAD` and `git rev-parse origin/main`
5. keep secrets only in ignored local env files
6. keep benchmark/scratch output under ignored `tmp/`
