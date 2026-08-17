---
name: test-driven-development
description: Write test first, watch it fail, write minimal code to pass. No exceptions.
---

# Test-Driven Development

## Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Code before test? **Delete it. Start over. No exceptions.**

- Don't keep as "reference"
- Don't "adapt" while writing tests
- Don't look at it
- **Delete means delete. Period.**

Implement fresh from tests only.

**Violating the letter of this rule is violating the spirit of this rule.**

## Test Strategy (Collaborative Decision)

Before writing ANY test, propose strategy to user:

### Strategy Proposal Template

```
Test strategy for [feature/bugfix]:

[What are we building? - 1 sentence]

Test Layers:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Unit Tests
   Scope: [What specific logic/function]
   Input: [What goes in]
   Output: [What comes out]
   Dependencies: [Real implementations - NO MOCKS unless impossible]
   Cover: [Happy path, edge cases, errors]
   Location: [File path]
 
   Why unit: [Reasoning - fast, isolated, specific logic]

2. Integration Tests
   Scope: [What components together]
   Real data: [Use fixtures, real DB, real files]
   Dependencies: [Real implementations - NO MOCKS]
   Cover: [Cross-component flows, data transformation]
   Location: [File path]
 
   Why integration: [Reasoning - component interaction, real system]

3. E2E Tests
   Scope: [Full user journey]
   Real system: [Everything real - NO MOCKS]
   Cover: [Actual user scenarios]
 
   Why e2e: [Reasoning - production confidence]

Recommended Approach:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Start with: [Which layer and why]
Sequence: [Order of implementation]
Trade-offs: [What we gain/lose]

Alternative Approaches:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Option A: [Different strategy]
  Pros: [Benefits]
  Cons: [Drawbacks]

Option B: [Another strategy]
  Pros: [Benefits]
  Cons: [Drawbacks]

Hangisini tercih edersin?
```

**Wait for user decision. Don't write test until strategy approved.**

## Mock Policy (Extreme Minimalism)

**Default: NO MOCKS. Use real implementations.**

### Only Mock When Physically Impossible

**Acceptable (can't avoid):**
- ✅ External paid API (costs money per call)
- ✅ External service you don't control (e-fatura gov API)
- ✅ Time/Date (for deterministic tests)
- ✅ Random number generation (for deterministic tests)
- ✅ Actual network calls in CI

**NOT acceptable (use real):**
- ❌ Your own database → Use test database
- ❌ Your own services → Use real implementations
- ❌ File I/O → Use real temp files
- ❌ Your own API client → Use real client with test API
- ❌ "It's easier to mock" → Not a reason

### When You Must Mock

**Dependency injection pattern ONLY:**

```python
# ✅ Good: Real by default, mockable when needed
class InvoiceService:
    def __init__(self, api_client: EFaturaAPI):
        self.api = api_client
  
    async def fetch(self, id: str):
        return await self.api.get(id)

# Test with REAL test API
def test_fetch_invoice():
    test_api = EFaturaAPI(base_url=TEST_API_URL)  # Real client, test server
    service = InvoiceService(api_client=test_api)
  
    result = await service.fetch("123")
    assert result.invoice_id == "123"

# Only mock if test API unavailable or costs money
def test_fetch_when_api_down():
    mock_api = Mock(spec=EFaturaAPI)
    mock_api.get.return_value = fake_invoice
    service = InvoiceService(api_client=mock_api)
  
    result = await service.fetch("123")
    assert result == fake_invoice
```

**If you're mocking, ask yourself:**
- Can I use a test database instead?
- Can I use real temp files instead?
- Can I use a fake implementation with real behavior?
- Am I mocking because I'm lazy?

**If answer to last question is yes: Don't mock. Use real.**

## Red-Green-Refactor Cycle

Once strategy approved, execute:

### RED Phase

**1. Write Failing Test**

Based on approved strategy:
- Test exactly what was agreed
- Use REAL dependencies (no mocks unless approved)
- Cover agreed edge cases
- Clear, descriptive test name

**Good test structure (Arrange-Act-Assert):**

```python
def test_parse_efatura_xml_extracts_invoice_data():
    # Arrange: Real XML file
    xml_content = Path('fixtures/valid_efatura.xml').read_text()
    parser = EFaturaParser()  # Real parser, no mocks
  
    # Act
    invoice = parser.parse(xml_content)
  
    # Assert
    assert invoice.invoice_id == "FTR2024000123"
    assert invoice.total_amount == Decimal("1250.00")
    assert invoice.currency == "TRY"
    assert len(invoice.line_items) == 3
```

**2. Verify RED - Watch It Fail**

**MANDATORY. Never skip.**

Run test - confirm:
- Test FAILS (not errors, not skips)
- Fails because feature missing (not typo, not wrong test)
- Failure message clear

**If test passes:** You're testing existing behavior (wrong test)

**If test errors:** Fix error, then verify RED

### GREEN Phase

**Write Minimal Code to Pass**

Implement ONLY what's needed:
- Don't add extra features
- Don't refactor other code
- Don't add "nice to have" logic
- Don't over-engineer

**Simplest implementation:**

```python
def parse(self, xml_content: str) -> Invoice:
    root = ET.fromstring(xml_content)
  
    return Invoice(
        invoice_id=root.find('.//cbc:ID').text,
        total_amount=Decimal(root.find('.//cbc:TaxInclusiveAmount').text),
        currency=root.find('.//cbc:TaxInclusiveAmount').attrib['currencyID'],
        line_items=self._parse_line_items(root)
    )
```

That's it. No more.

**Verify GREEN - Watch It Pass**

**MANDATORY.**

Run test - confirm:
- Test PASSES
- All other tests still pass
- No warnings, no errors

Run full suite - no regressions.

### REFACTOR Phase

**Clean Up (Keep Tests Green)**

After green only:
- Remove duplication
- Better names
- Extract helpers
- Simplify logic

**BUT:**
- Tests stay green after each change
- Don't add new behavior (needs new test)
- Don't refactor unrelated code

Run tests after each refactor. Stay green.

## Test Strategy Patterns

### Pattern 1: Outside-In (E2E → Unit)

Start with integration/e2e test (fails), then write unit tests for components.

**When:** Complex feature, multiple components

### Pattern 2: Inside-Out (Unit → Integration)

Start with unit tests for core logic, then integration.

**When:** Clear single responsibility, well-defined I/O

### Pattern 3: Spike Then Delete

Explore with throwaway code, then TDD properly.

**When:** Unfamiliar API, need exploration

**Spike = exploration. Delete before TDD. No exceptions.**

### Pattern 4: Characterization (Legacy)

Fixing bugs in untested code:

1. Write test capturing CURRENT behavior (even if wrong)
2. Test passes (GREEN - but behavior buggy)
3. Modify test for CORRECT behavior (RED)
4. Fix code (GREEN)

## Edge Cases and Errors

Test strategy must cover:

**Happy path:** Valid input → expected output

**Edge cases:** Empty input, null values, boundary values, special characters, large data

**Error cases:** Invalid input, missing fields, external failure, timeout

## Test Naming

Pattern: `test_[what]_[does_what]_[condition]`

```python
# ✅ Good
def test_parse_efatura_extracts_line_items_with_vat():
def test_upload_invoice_creates_workflow_record():
def test_invalid_xml_raises_parse_error():

# ❌ Bad
def test_parser():
def test_invoice():
def test_error():
```

## Verification Checklist

Before claiming complete:

- [ ] **Test strategy proposed and approved**
- [ ] **Using REAL dependencies (no unnecessary mocks)**
- [ ] **Watched test fail** (RED verified)
- [ ] **Failed for right reason** (feature missing, not typo)
- [ ] **Wrote minimal code** to pass
- [ ] **Watched test pass** (GREEN verified)
- [ ] **All tests pass** (no regressions)
- [ ] **Output pristine** (no errors, warnings)
- [ ] **Refactored if needed** (stayed green)

Can't check all? Don't claim complete.

## Common Rationalizations (REJECT ALL)

| Excuse | Reality | Response |
|--------|---------|----------|
| "Too simple to test" | Simple breaks | Test takes 30 seconds |
| "I'll test after" | Tests after prove nothing | Delete code, test first |
| "Manually tested" | Ad-hoc ≠ systematic | Automate or didn't happen |
| "Skip RED verification" | Can't prove test works | RED proves test catches bugs |
| "Hard to test" | Design wrong | Hard to test = hard to use |
| "Just this once" | Exception becomes habit | No exceptions. Period. |
| "Keep as reference" | You'll adapt it | Delete means delete |
| "Mock is easier" | Not a reason | Use real unless impossible |
| "Test DB is slow" | Not compared to debugging | Use real database |

**All mean: STOP. Follow TDD. No shortcuts.**

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write wished-for API. Ask user. |
| Test complicated | Design complicated. Simplify. |
| Want to mock everything | Code too coupled. Fix design. |
| Test slow | Too much I/O? Still use real. Optimize later. |
| Test flaky | Race condition. Fix or use real time mock. |

## Bug Fixes

**Bug found?**

1. Propose test strategy: "What test catches this?"
2. Write failing test reproducing bug (RED)
3. Verify fails with bug present
4. Fix bug (GREEN)
5. Verify passes

**Never fix bugs without regression test. Period.**

## Integration with Other Skills

After TDD complete:
- Use `verification-before-completion` for final check
- Document complex test strategy in comments

Don't:
- Skip TDD because "plan has tests"
- Skip strategy proposal

**User decides strategy. Always.**

---

**End of TDD Skill**
