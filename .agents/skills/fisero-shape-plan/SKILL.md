---
name: fisero-shape-plan
description: Turn a material Fisero product, architecture, workflow, provider, or implementation question into an evidence-backed decision the user can make. Use when the user says once konusalim, netlestirelim, plan yapalim, kod degisikligi yapma, asks what should be built next, or when multiple viable approaches have meaningful product or long-term tradeoffs.
---

# Shape a Fisero Decision

## Establish truth

Inspect the current implementation, canonical product decisions, and relevant
runtime evidence before recommending change. Label facts, assumptions,
inferences, and unknowns separately.

Do not edit files while the user is still discussing or clarifying the plan.

## Frame the decision

State the actual decision in one sentence. Exclude questions already settled by
the user. Describe the affected accountant job, system boundary, and success
criterion.

## Develop options

Offer only realistic alternatives. Include the smallest viable option when it
is genuinely viable. For each option evaluate:

- user and accountant value;
- implementation and operational cost;
- risk and reversibility;
- effect on maintainability and scale;
- what it postpones or makes harder later.

Do not create false balance. Reject an option plainly when evidence makes it
unreasonable.

## Recommend and hand over

Give a direct recommendation and why it wins. Explain the internal system logic
at the user's technical altitude so the decision also teaches the user.

End with:

- decisions the user must make;
- acceptance criteria;
- verification plan;
- commit, push, and deploy boundaries.

Use [references/decision-format.md](references/decision-format.md) as the output
shape for substantial decisions.
