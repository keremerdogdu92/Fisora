---
name: using-superpowers
description: Use when starting work, selecting workflow skills, or deciding whether an ambiguous request needs a structured process.
---

# Using Superpowers

Check relevant skills before starting work.

## Always-active gates

Apply these whenever their condition occurs:

- `using-superpowers`: before work begins, select the applicable skills.
- `verification-before-completion`: before any completion, passing, fixed, or ready claim.

They are default behavior once available; the user does not need to name them.

## Use immediately

Use a skill without asking when the user names it or the trigger is clear.

| Trigger | Skill |
| --- | --- |
| new feature, build, design, brainstorm | `brainstorming` |
| bug, failure, root cause, debug | `systematic-debugging` when installed |
| plan, decide, clarify, discuss first | `fisero-shape-plan` or `writing-plans`, according to scope |
| commit, push, deploy, release | `fisero-release-handoff`; respect `Manual Release` in `AGENTS.md` |
| implementation or bug fix | `test-driven-development` |
| execute an approved plan inline | `executing-plans` |
| execute independent plan tasks with agents | `subagent-driven-development` |

## Resolve ambiguous triggers

Ask one focused question only when the answer materially changes the workflow.

- `refactor`: use `brainstorming` for a design-level refactor; use
  `test-driven-development` directly for a bounded behavior-preserving change.
- `write tests`: use `brainstorming` then TDD for a new feature; use TDD directly
  for existing behavior or a regression.
- multi-step request with unclear outcome: ask which outcome is authoritative,
  then select the skill.

Do not ask merely because a skill exists. Inspect local context first when it
can resolve the ambiguity safely.

## Priority

Apply process skills before implementation skills:

1. `brainstorming` or `systematic-debugging`
2. `writing-plans`
3. `test-driven-development`
4. `executing-plans` or `subagent-driven-development`
5. `verification-before-completion`

Project instructions and direct user decisions override skill defaults. A skill
never authorizes commit, push, deploy, destructive actions, or production writes.
