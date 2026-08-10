# Testing Anti-Patterns

Use this reference when a test introduces mocks, fakes, test utilities, or
production seams solely for testing.

## Testing mock behavior

Bad: assert only that `mock.upload()` was called.

Better: assert the service's observable result, stored state, emitted contract,
or error behavior. A mock call may be a secondary assertion, never the proof of
the feature.

## Test-only production methods

Do not add `_for_test`, debug getters, or public escape hatches solely so a test
can inspect internals. Exercise the public contract. If the public contract
cannot express the behavior, reconsider the design boundary.

## Mocking code you control

Do not replace all internal collaborators with mocks and then claim the system
works. Use real parsers, domain services, transformations, and representative
fixtures. Add a focused unit test only where isolation proves a distinct rule.

## Mocking persistence

When testing repository queries, transactions, constraints, or serialization,
use an isolated real database. A dictionary fake cannot prove SQL behavior.

When testing a pure service decision above persistence, a behavioral in-memory
repository may be appropriate if the database contract is separately covered.

## Over-mocking external dependencies

Prefer a provider's sandbox or local protocol fake when safe and deterministic.
Mock the external boundary when calls cost money, require secrets, are unstable,
or are prohibited in CI. Preserve representative request and response shapes.

## Testing implementation details

Avoid assertions about private call order, helper names, or internal method
counts unless that order is itself the public contract. Refactoring should not
break a behavior-preserving test.

## Time and randomness

Inject a clock or random source and control it deterministically. Do not sleep in
tests or depend on wall-clock timing when a controllable boundary is available.

## Quick decision

Before adding a mock, answer:

1. Is the real dependency unsafe, paid, unavailable, or nondeterministic?
2. Can a real temporary resource or behavioral fake prove more?
3. Does the assertion verify user-visible/domain behavior?
4. Is the real integration contract tested elsewhere?

If the first answer is no, prefer the real implementation.
