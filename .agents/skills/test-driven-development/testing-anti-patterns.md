# Testing Anti-Patterns

Referenced by `test-driven-development` skill.

## Anti-Pattern 1: Testing Mock Behavior

**Problem:** Test verifies mock was called, not that code works.

❌ **Bad:**
```python
def test_upload_invoice():
    mock_storage = Mock()
    mock_storage.upload.return_value = "blob-url"

    service.storage = mock_storage
    service.upload(file)

    assert mock_storage.upload.called  # Testing mock, not service
```

✅ **Good:**
```python
def test_upload_invoice():
    real_test_storage = BlobStorage(container="test-uploads")
    service = InvoiceService(storage=real_test_storage)

    result = service.upload(file)

    assert result.url.startswith("https://")
    assert real_test_storage.exists(result.blob_id)

    # Cleanup
    real_test_storage.delete(result.blob_id)
```

---

## Anti-Pattern 2: Test-Only Methods in Production

**Problem:** Adding methods to production classes just for testing.

❌ **Bad:**
```python
class InvoiceParser:
    def parse(self, xml):
        data = self._extract_data(xml)
        return self._build_invoice(data)

    # Added ONLY for testing
    def _extract_data_for_test(self, xml):
        return self._extract_data(xml)
```

✅ **Good:**
```python
class InvoiceParser:
    def parse(self, xml):
        data = self._extract_data(xml)
        return self._build_invoice(data)

    # Test the PUBLIC interface only

# Test:
def test_parse():
    result = parser.parse(xml)
    assert result.invoice_id == "123"  # Test output, not internals
```

---

## Anti-Pattern 3: Mocking What You Control

**Problem:** Mocking your own code instead of testing it.

❌ **Bad:**
```python
def test_process_invoice():
    mock_parser = Mock()
    mock_parser.parse.return_value = fake_invoice

    mock_matcher = Mock()
    mock_matcher.match.return_value = fake_accounts

    service.parser = mock_parser
    service.matcher = mock_matcher

    result = service.process(xml)

    # You tested nothing real
```

✅ **Good:**
```python
def test_process_invoice():
    # Use REAL implementations
    parser = InvoiceParser()
    matcher = AccountMatcher(chart=test_chart)
    service = InvoiceService(parser=parser, matcher=matcher)

    result = service.process(real_xml)

    # Actually tested the system
    assert result.status == "matched"
    assert len(result.matched_accounts) == 3
```

---

## Anti-Pattern 4: Over-Mocking External Dependencies

**Problem:** Mocking things that have test modes.

❌ **Bad:**
```python
def test_save_to_database():
    mock_db = Mock()
    mock_db.insert.return_value = True

    service.db = mock_db
    service.save(invoice)

    assert mock_db.insert.called  # Tested mock, not DB interaction
```

✅ **Good:**
```python
async def test_save_to_database():
    # Use REAL test database
    test_db = await create_test_database()
    service = InvoiceService(db=test_db)

    await service.save(invoice)

    # Verify in REAL database
    saved = await test_db.get_invoice(invoice.id)
    assert saved.total == invoice.total

    # Cleanup
    await test_db.cleanup()
```

---

## Anti-Pattern 5: Testing Implementation Details

**Problem:** Test breaks when you refactor (even though behavior unchanged).

❌ **Bad:**
```python
def test_parser_calls_extract_then_transform():
    parser = InvoiceParser()

    with patch.object(parser, '_extract') as mock_extract:
        with patch.object(parser, '_transform') as mock_transform:
            parser.parse(xml)

            mock_extract.assert_called_once()
            mock_transform.assert_called_once()
            # Breaks if you change internal implementation
```

✅ **Good:**
```python
def test_parser_extracts_invoice_data():
    parser = InvoiceParser()

    result = parser.parse(xml)

    # Test behavior, not implementation
    assert result.invoice_id == "FTR123"
    assert result.total == Decimal("1250.00")
    # Works regardless of internal refactoring
```

---

## When Mocking IS Appropriate

**Only when physically impossible to use real:**

1. **External paid API:**
```python
def test_fetch_from_government_api():
    # Can't call real API (costs money, rate limits)
    mock_api = Mock(spec=GovAPI)
    mock_api.fetch.return_value = sample_response

    service = Service(api=mock_api)
    result = service.fetch("123")

    assert result.validated
```

2. **Time/Date for deterministic tests:**
```python
def test_generate_report_with_timestamp(freezegun):
    # Freeze time for predictable test
    freezegun.freeze("2024-01-15 10:30:00")

    report = generate_daily_report()
    assert report.timestamp == datetime(2024, 1, 15, 10, 30)
```

3. **Random for deterministic tests:**
```python
def test_generate_invoice_id(monkeypatch):
    # Fix random for predictable test
    monkeypatch.setattr('random.randint', lambda a, b: 12345)

    invoice_id = generate_id()
    assert invoice_id == "INV-12345"
```

**Everything else: Use real implementations.**
