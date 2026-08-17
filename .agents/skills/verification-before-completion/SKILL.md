---
name: verification-before-completion
description: Use before claiming work is complete, fixed, passing, ready, or safe to hand off.
---

# Verification Before Completion

## Iron Law

```text
NO COMPLETION CLAIM WITHOUT FRESH, RELEVANT EVIDENCE
```

## Gate

Before claiming success, moving to the next task, or asking the user whether a
problem is solved:

1. Identify the command or observation that proves the claim.
2. Run it freshly at the scope required by the change.
3. Read the exit code, pass/fail counts, and relevant output.
4. Compare the result with every acceptance criterion.
5. Report the command, exit code, concise result, anything unverified, and the
   actual state.

Show full raw output when verification fails or the user requests it. Otherwise
report only the evidence needed to support the claim.

Partial evidence proves only its own scope. A linter does not prove a build; a
passing job does not prove accounting correctness; a subagent report does not
replace inspecting the diff.

## When verification fails

- Do not soften the claim with “probably” or “should”.
- Report the exact failing command, symptom, and relevant raw output.
- If `systematic-debugging` is installed, use it before proposing a fix.
- Otherwise trace the failure from evidence and label the task incomplete.
- After a fix, rerun the failed check and the relevant regression scope.

## Required evidence by claim

| Claim | Evidence |
| --- | --- |
| Test passes | Fresh test output with zero failures |
| Build succeeds | Build command exit code 0 |
| Bug fixed | Original symptom or regression test passes |
| Requirement complete | Requirement-by-requirement inspection |
| Skill valid | Frontmatter/structure validation and behavior review |
| Agent task complete | Diff inspection plus independent verification |

## Skill Integration

- `test-driven-development`: verify RED, GREEN, and post-refactor GREEN.
- `systematic-debugging`: verify the fix before asking “Çözüldü mü?”. If the
  user says no, return to debugging rather than claiming completion.
- `writing-plans`: verify each task against its acceptance criterion before
  advancing.

Never commit, push, deploy, or mutate production as part of verification. Those
actions remain manual user responsibilities.
