---
name: writing-plans
description: Use when approved requirements or a specification must become a multi-step implementation plan before code changes.
---

# Writing Plans

Create a self-contained, executable plan for an engineer with no session
context. Keep the plan concise; include only information needed to implement
and verify the approved behavior.

## Workflow

1. Read the approved specification and current implementation evidence.
2. Split independent subsystems into separate plans when useful.
3. Map exact files and the responsibility of each changed unit.
4. Divide work into independently verifiable tasks.
5. Define interfaces, acceptance criteria, and verification for every task.
6. Self-review coverage, paths, interfaces, placeholders, and contradictions.

## Plan Contract

Include:

- goal, approach, approved constraints, and non-scope;
- exact files;
- interfaces consumed and produced;
- observable acceptance criteria;
- failing test and expected RED evidence;
- minimal implementation step;
- GREEN and regression commands;
- exact commands and expected evidence.

Do not reproduce full implementations. Include an exact signature, critical
algorithm, schema, or short code snippet only when prose would leave the task
ambiguous.

## Quality Gate

- No `TBD`, `TODO`, “handle errors”, “add tests”, or similar placeholders.
- Do not invent requirements not present in the approved design.
- Keep type names, function signatures, schema fields, and exact values
  consistent across tasks.
- Every approved requirement must map to a task and verification step.
- Plans must not contain commit, push, deploy, PR, or production actions.

## Handoff

After presenting the plan, ask the user to choose:

1. `executing-plans` for sequential or tightly coupled tasks.
2. `subagent-driven-development` for independent tasks.

Use generic skill names. Save the plan only in the project-approved location;
otherwise keep it in the conversation. The user handles release actions.
