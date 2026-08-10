---
name: subagent-driven-development
description: Use when an approved implementation plan contains independent tasks that benefit from fresh subagent contexts and review gates.
---

# Subagent-Driven Development

Use fresh subagents for independent tasks while the main agent owns integration,
scope, and final verification.

## Preconditions

- The plan is approved and tasks have non-overlapping ownership.
- Each task has exact files, acceptance criteria, and verification commands.
- Subagents are available.
- No task requires an unapproved external or production action.

Use `executing-plans` instead when tasks are tightly coupled or one task's design
depends on unfinished work from another.

## Workflow

1. Review the plan for conflicts and define file ownership.
2. Dispatch one implementer per independent task with only the context it needs.
3. Tell every implementer that others share the workspace, unrelated edits must
   be preserved, and release actions are forbidden.
4. Require `test-driven-development` and an exact test report.
5. Inspect each task's diff and verification evidence.
6. Send material findings back for correction and re-review.
7. Integrate completed tasks and run whole-change verification.
8. Use `verification-before-completion` before reporting status.

Parallel implementers are allowed only when their file ownership cannot overlap.
Serialize tasks that share files, schemas, migrations, generated artifacts, or
runtime state.

## Implementer report

Require:

- status: `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`;
- files changed;
- RED and GREEN evidence;
- regression command and result;
- unresolved concerns.

Do not trust the report alone. The main agent verifies the diff and reruns checks
in proportion to risk.

## Stop conditions

Stop and return to the user only when:

- a missing decision materially changes the result;
- the plan conflicts with project instructions;
- a required external action lacks authority;
- repeated verification cannot resolve a blocker.

Subagents and the main agent must not commit, push, deploy, create PRs, or mutate
production. The user performs release actions manually.
