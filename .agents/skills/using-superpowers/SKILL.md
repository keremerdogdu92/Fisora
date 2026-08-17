---
name: using-superpowers
description: Check for relevant skills before starting work, ask user if unsure
---

# Using Superpowers

Check for relevant skills before starting work.

## Always-Active Skills

These skills run automatically in every session, no explicit invoke needed:

- **verification-before-completion**: Runs before any completion claim (evidence before claims)
- **using-superpowers**: Runs before starting work (this skill)

You don't invoke these. They're part of default behavior.

## When to Use vs Ask

**Use immediately (don't ask):**

User explicitly names skill or uses trigger keywords:

| Trigger Keywords | Skill |
|-----------------|-------|
| "yeni feature", "build", "tasarla", "brainstorm" | brainstorming |
| "bug", "neden oldu", "fix", "debug", "sorun" | systematic-debugging |
| "plan yap", "önce konuş", "netleştir", "karar ver" | brainstorming |
| "TDD", "test yaz", "red-green" | test-driven-development |

Commit, push, deploy, and release requests follow `Manual Release` in
`AGENTS.md`: prepare changes or evidence only; do not perform release actions.

**Ambiguous keywords (ask user):**

- **"refactor"** → Large refactoring (multiple components) = brainstorming, Small refactoring (single function) = TDD. Ask: "Büyük refactoring mi (tasarım değişikliği) yoksa küçük refactoring mi (tek fonksiyon)?"

- **"test yaz"** → For new feature = brainstorming + TDD, For existing code = TDD directly. Ask: "Yeni feature için mi (önce tasarım) yoksa mevcut kod için mi (direkt test)?"

- **Unclear context** → Ask user which skill or proceed without skill

**Ask user first:**
- Skill might help but value unclear
- Multi-step change without clear trigger keyword
- Example: "Bu değişiklik multi-step. Brainstorming skill ile tasarım yapayım mı?"

**Proceed without skill:**
- Simple, single-file changes
- User says "direkt yap", "skill kullanma"

## Skill Priority

When multiple skills apply, process skills come first:
- brainstorming → sets approach
- systematic-debugging → finds root cause
- writing-plans → creates implementation plan

Then implementation skills (TDD, verification).

## Red Flags (You're Rationalizing)

- "This is too simple for a skill" → Check trigger keywords or ask
- "I'll start then maybe use skill" → Check BEFORE starting
- "Skills are overkill" → Let user decide

## Platform Note

User instructions (AGENTS.md, CLAUDE.md, direct requests) override skills.
Skip skill workflows only when user explicitly tells you to.
