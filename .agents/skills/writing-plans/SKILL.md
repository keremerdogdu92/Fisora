---
name: writing-plans
description: Use when approved requirements or a specification must become a multi-step implementation plan before code changes.
---

# Writing Plans

Create an executable plan for an engineer who has not read the current session.

## Workflow

1. Read the approved specification and current implementation evidence.
2. Map files to create, modify, and test, with one responsibility per unit.
3. Split work into independently verifiable tasks.
4. For each behavior change, use RED-GREEN-REFACTOR steps.
5. Include exact commands and expected evidence.
6. Self-review coverage, placeholders, paths, interfaces, and contradictions.
7. Save material plans to
   `docs/superpowers/plans/YYYY-MM-DD-<topic>-implementation.md` unless the user
   chooses another location.

## Required plan header

```markdown
# <Topic> Implementation Plan

**Goal:** <one observable outcome>
**Approach:** <two or three sentences>
**Constraints:** <approved non-scope and safety boundaries>
**Verification:** <targeted and regression commands>
```

## Task shape

Each task must contain:

- exact files;
- protected rule or acceptance criterion;
- interfaces consumed and produced;
- failing test and expected RED evidence;
- minimal implementation step;
- GREEN and regression commands;
- completion evidence.

Use checkboxes for execution tracking. Keep each task large enough to produce a
coherent result and small enough for independent review.

## Quality rules

- No `TBD`, `TODO`, “handle errors”, “add tests”, or similar placeholders.
- Do not invent requirements not present in the approved design.
- Do not repeat the same code or instruction across tasks; define the interface
  once and reference it.
- Keep type names, function signatures, schema fields, and exact values
  consistent across tasks.
- Use generic skill names such as `test-driven-development`,
  `executing-plans`, and `subagent-driven-development`; do not assume an
  external namespace.

## Execution handoff

- Independent tasks in the current session: `subagent-driven-development`.
- Sequential or tightly coupled tasks: `executing-plans`.

Plans must not contain commit, push, deploy, PR, or production-mutation steps.
The user performs release actions manually.
