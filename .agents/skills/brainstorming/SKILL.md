---
name: brainstorming
description: Use when creating a feature, component, workflow, or behavior change before implementation begins.
---

# Brainstorming

Turn an idea into an approved design before code changes.

## Hard gate

Do not write implementation code until the design is approved. Direct user
approval of an already-specific design satisfies this gate; do not reopen
settled decisions without material conflicting evidence.

## Workflow

1. Inspect current files, documentation, and relevant recent history.
2. Identify the user outcome, constraints, non-scope, and success criteria.
3. Ask one focused question at a time only for result-changing unknowns.
4. Present two or three realistic approaches with costs, risks, reversibility,
   and a direct recommendation.
5. Present the chosen design at the depth needed for the task.
6. Get explicit approval.
7. For a material design, write the approved specification to
   `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` unless the user selects
   another location.
8. Self-review the specification for placeholders, contradictions, scope, and
   ambiguity.
9. Use `writing-plans` for implementation planning.

## Design rules

- Give each unit one clear responsibility and a defined interface.
- Prefer small, independently testable boundaries.
- Follow established project patterns.
- Improve only code that materially affects the requested work.
- Decompose multiple independent subsystems into separate specifications.
- Apply YAGNI: exclude work that is not needed for the approved outcome.

## Handoff

After specification approval, choose the execution method from task structure:

- Mostly independent tasks in this session: `subagent-driven-development`.
- Sequential or tightly coupled tasks: `executing-plans`.

Do not depend on a platform-specific visual companion. Use available tools only
when they materially improve the decision.
