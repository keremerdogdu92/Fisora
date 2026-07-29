# Fisero Release Proof

## Local proof

Use tests proportional to scope. The stable full set is:

```powershell
python -m unittest discover -s backend/tests
node --test frontend/app/*.test.cjs
Push-Location frontend
npm.cmd run build
Pop-Location
git diff --check
```

When deploy configuration changes, validate the production Compose
configuration. When migrations change, run the repository's current migration
dry-run or compatibility proof before the release gate.

## Git proof

Inspect:

```powershell
git status -sb
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-list --left-right --count HEAD...origin/<branch>
```

Stage with explicit paths. Never use blanket staging in a mixed worktree.
Recheck the staged diff before committing.

Prefer fast-forward history and normal pushes. A force-push or history rewrite
requires a newly disclosed decision and is not covered by normal release
approval.

## Release wrapper

Preferred entrypoint:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/scripts/fisora-release.ps1
```

Useful flags:

- `-PlanOnly -Json`: compact read-only release plan;
- `-SkipLocalVerify`: reuse proof completed in the same turn;
- `-AllowDirty`: tolerate unrelated local artifacts without staging them;
- `-SkipSmoke`: use only when the approved transaction explicitly narrows proof;
- `-NoSudo`: use only if the server checkout ownership model changed.

Read the live script and `docs/current-handoff.md` before relying on cached
server, key, path, branch, or URL facts.

## Live proof

HTTP 200 alone is insufficient. Confirm:

- server checkout branch and commit;
- release check/deploy/smoke result;
- `/health`;
- `/api/phase0/store/system/readiness`;
- affected public route or API behavior;
- local/remote/server parity.

For portal workspace performance, verify the summary payload before requesting
the full workspace. For review, upload, learning, or processing discrepancies,
start from `workflow_records`.

## Failure handling

- Permission denied in server Git: verify current checkout ownership and
  approved sudo path; do not improvise credential changes.
- Non-fast-forward or conflict: stop and present the divergence.
- Dirty worktree: identify intentional scope and excluded files; never clean
  unrelated work.
- Readiness parsing or nested quoting failure: use direct HTTP plus local JSON
  parsing.
- Runtime deploy commit differs from a later handoff-only parity commit: report
  both explicitly.
- Partial release: list the last successful mutation and the safest recovery
  point; do not claim completion.
