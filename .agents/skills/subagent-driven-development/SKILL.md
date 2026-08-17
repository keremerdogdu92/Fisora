---
name: subagent-driven-development
description: Use when an approved implementation plan contains independent tasks that benefit from fresh subagent contexts and review gates.
---

# Subagent-Driven Development

Use fresh subagents for independent tasks. The main agent owns scope,
integration, technical review, and final verification.

## Preconditions

- The plan is approved.
- Tasks have exact files, non-overlapping ownership, acceptance criteria, and
  verification commands.
- Subagents are available.
- No task requires an unapproved external or production action.

Use `executing-plans` instead when tasks are tightly coupled or one task's design
depends on unfinished work from another.

## Workflow

1. Define task dependencies and exclusive file ownership.
2. Dispatch one implementer per independent task with only required context.
3. Require preservation of unrelated work and forbid release actions.
4. Require `test-driven-development` and concise RED/GREEN evidence.
5. Inspect every diff; never trust a subagent report alone.
6. Return technical defects to the subagent and re-review without asking the
   user to approve each task.
7. Integrate accepted work and run whole-change verification.
8. Apply `verification-before-completion` before reporting status.

Parallelize only tasks whose files and mutable state cannot overlap. Serialize
shared files, schemas, migrations, generated artifacts, and runtime state.

## Ask the User Only When

- a missing decision materially changes the result;
- the plan conflicts with project instructions;
- an ownership conflict cannot be resolved safely by serialization;
- a required external action lacks authority;
- repeated debugging and verification cannot resolve a blocker.

Do not add per-task approval prompts or periodic checkpoints. Provide concise,
non-blocking progress only when useful.

Subagents and the main agent must not commit, push, deploy, create PRs, or mutate
production. The user performs release actions manually.
