---
name: test-driven-development
description: Use when implementing a feature, bug fix, refactor, or behavior change before production code is written.
---

# Test-Driven Development

## Iron law

```text
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Code written first must not guide the test. Remove it and implement again from
the failing test. Violating the letter of this rule violates its purpose.

## Agree the test strategy

Before the first test, show the user a concise strategy for meaningful changes:

```text
Protected rule: <observable behavior or invariant>
Primary layer: <Unit/Domain | Integration/API | UI/E2E>
Why this layer: <why it gives the smallest reliable proof>
Dependencies: <real implementations; unavoidable doubles and why>
RED proof: <command and expected failure>
GREEN proof: <targeted command and broader regression check>
```

Offer alternatives only when they materially change cost, speed, or confidence.
Wait for approval when the strategy changes scope, uses paid/live services,
requires persistent data, or the user explicitly asks to decide the strategy.
For a settled low-risk strategy, state it and proceed without a redundant pause.

## Choose the layer

| Layer | Use for | Evidence |
| --- | --- | --- |
| Unit/Domain | Pure rules, calculations, parsing, invariants | Deterministic input/output |
| Integration/API | Boundaries, persistence, serialization, component flow | Real adapters and representative fixtures |
| UI/E2E | Accountant-visible journeys and browser behavior | Real rendered workflow |

Start at the lowest layer that proves the rule. Add broader layers only for a
distinct risk.

## Mock minimalism

Default to real behavior:

- use real domain objects and services you control;
- use real temporary files for file I/O;
- use representative XML/PDF fixtures;
- use an isolated test database when persistence behavior is the subject;
- prefer a behavioral fake over interaction-only mocks.

Use a mock or test double only when the real boundary is impractical or unsafe:

- paid or rate-limited external API;
- government or third-party system without a safe test mode;
- actual network calls prohibited in CI;
- time or randomness requiring deterministic control;
- failure injection that cannot be produced safely with the real dependency.

When using a double, test the behavior at your boundary, not that the mock was
called. Read [testing-anti-patterns.md](testing-anti-patterns.md).

## RED-GREEN-REFACTOR

### RED

1. Write one minimal test for the approved behavior.
2. Use a clear name describing the outcome and condition.
3. Run the targeted test.
4. Confirm it fails, not errors or skips.
5. Confirm the failure is caused by missing/wrong behavior.

If the test passes immediately, it does not prove the new behavior. Correct the
test or establish that no implementation change is required.

### GREEN

1. Write the smallest production change that satisfies the failing test.
2. Run the targeted test and confirm it passes.
3. Run the relevant regression scope.
4. Fix production code when the agreed behavior is unmet; do not weaken the test.

### REFACTOR

After green only:

- remove duplication;
- improve names and boundaries;
- keep behavior unchanged;
- rerun the tests after each meaningful refactor.

New behavior requires a new RED cycle.

## Bug fixes and legacy code

For a bug:

1. Reproduce it with a failing regression test.
2. Verify the failure matches the reported symptom.
3. Apply the smallest fix.
4. Verify targeted and regression tests.

For legacy code whose current behavior must first be captured:

1. Write a characterization test and observe it pass.
2. Change the assertion to the required behavior and observe RED.
3. Implement the fix and observe GREEN.

Exploratory spikes are allowed only as throwaway learning. Remove the spike
before starting the real RED cycle.

## Red flags

- production code before the failing test;
- test added after implementation;
- RED not observed or explained;
- mock assertions replacing behavior assertions;
- weakening a test to make code pass;
- unrelated refactoring during GREEN;
- claiming manual checks are equivalent to repeatable tests.

Stop and restore the RED-GREEN sequence when any red flag occurs.

## Completion checklist

- [ ] Test strategy was communicated at the required depth.
- [ ] The protected rule and test layer are explicit.
- [ ] Unavoidable doubles are justified.
- [ ] RED was observed for the right reason.
- [ ] Minimal implementation produced GREEN.
- [ ] Relevant regressions pass.
- [ ] Refactoring, if any, stayed green.
- [ ] Fresh evidence is reported through `verification-before-completion`.

Testing never authorizes commit, push, deploy, or live data mutation.
