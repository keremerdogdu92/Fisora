---
name: executing-plans
description: Use when an approved implementation plan has sequential or tightly coupled tasks to execute in the current session.
---

# Executing Plans

Execute an approved plan sequentially in the current session.

## Preflight

1. Read the complete plan and binding project instructions.
2. Inspect the current worktree and preserve unrelated changes.
3. Identify contradictions, missing inputs, dependencies, and external effects.
4. Create task tracking and start only when the plan is executable.

An explicit user instruction to execute on the current branch authorizes local
edits there. It never authorizes release actions.

## Per task

1. Mark the task in progress.
2. Apply `test-driven-development` for behavior changes.
3. Follow the approved scope; do not add speculative improvements.
4. Run the task's targeted verification.
5. Inspect the diff for unintended changes.
6. Mark the task complete only with fresh evidence.
7. Give a concise, non-blocking progress update when useful, then continue.

Do not add periodic checkpoints or ask “continue?” after a fixed number of
tasks.

If a task fails, do not skip it or stack speculative fixes. Use
`systematic-debugging`, verify the root-cause fix, then continue only when the
task's acceptance criterion passes.

## Ask the User Only When

- a requirement is ambiguous;
- the approved scope may change;
- an architecture or product decision is required;
- a test failure remains unresolved after systematic debugging;
- an external action or new authority is required.

## Completion

1. Run the plan's regression and build checks.
2. Use `verification-before-completion`.
3. Report completed scope, exact evidence, and remaining gaps.
4. Leave the working tree prepared for the user's manual release.

Do not commit, push, deploy, create a PR, or mutate production.
