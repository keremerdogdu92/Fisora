---
name: brainstorming
description: Turn ideas into designs through dialogue before implementation
---

# Brainstorming

Design first, code after.

## Process Flow

1. **Explore context:** Check files, docs, recent commits
2. **Ask questions:** One at a time, understand purpose/constraints/success
3. **Propose approaches:** 2-3 options with trade-offs, recommend one
4. **Present design:** In sections, get approval per section
5. **Write spec:** Save to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
6. **Self-review:** Check placeholders, contradictions, scope
7. **User reviews:** Ask user to review spec file
8. **Transition:** Ask which execution approach, then invoke appropriate skill

## Hard Gate

**DO NOT write code until design approved.**

No implementation skills (frontend-design, mcp-builder, etc.) until after `writing-plans`.

## Design Principles

**Isolation and clarity:**
- Each unit: one clear purpose, well-defined interfaces
- Can you understand/test each unit independently?
- If file grows large, it's doing too much

**Existing codebases:**
- Follow established patterns
- Improve code you touch, don't refactor unrelated code

**Scope check:**
- Multiple independent subsystems? Decompose into sub-projects first
- Each sub-project gets own spec → plan → implementation cycle

## Spec Self-Review

After writing spec, check:
- [ ] Placeholders? (TBD, TODO, "fill in details") → Fix them
- [ ] Contradictions? → Resolve
- [ ] Scope too large? → Decompose
- [ ] Ambiguous requirements? → Make explicit

Fix issues inline, then ask user to review.

## Execution Handoff

After user approves spec, ask:

> "Spec onaylandı. İki execution seçeneği var:
> 
> 1. **Subagent-Driven** - Her task için fresh subagent, aralarında review
> 2. **Inline Execution** - Bu session'da step-by-step execution
> 
> Hangisini tercih edersin?"

Then:
- User chooses subagent → Proceed with subagent approach (if available)
- User chooses inline → Invoke `writing-plans` skill to create detailed plan

**Do NOT invoke other implementation skills directly.**
