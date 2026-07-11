# QNB Incoming e-Fatura Integration Design

**Goal:** Bring incoming QNB eSolutions e-Fatura documents into Fisora as canonical UBL XML documents, then process them through the existing storage, parser, review, and export-gate flow.

**Status:** Phase 1 core implemented on 2026-07-08. Real TEST2 login and an
empty incoming-list smoke passed; a real sandbox document download and the
remaining end-to-end phases are tracked in
`docs/superpowers/plans/2026-07-10-qnb-end-to-end-integration.md`.

**References:**
- QNB API technical page: https://www.qnbesolutions.com.tr/destek/api-teknik
- QNB API documentation entrypoint: https://www.qnbesolutions.com.tr/api-docs-tr-final.html

---

## Decisions

### Phase Scope

Phase 1 covers only incoming e-Fatura intake from QNB.

Included:
- Per-client QNB connection credentials.
- Minimal QNB connection section in the client settings/detail surface.
- Required connection test before sync is enabled.
- Manual "QNB'den gelen e-Faturalari al" action in the portal.
- Date-range based incoming e-Fatura listing.
- Duplicate detection before download/import.
- UBL XML download.
- Storage through the existing Fisora document storage path.
- Creation of `uploaded_document` and `processing_job` records.
- Existing XML preview, XML parser, accounting draft, review gate, and export gate.
- Sync-run and pipeline evidence that the document came from QNB.

Excluded from Phase 1:
- Outgoing e-Fatura.
- e-Arsiv.
- Invoice sending, cancellation, rejection actions, and reply workflows.
- Scheduled sync.
- PDF download and direct PDF preview.
- Automatic export enablement.
- Full QNB administration UI.

Phase 1.5 adds QNB status reconciliation for already-imported documents.

Phase 2 adds per-client scheduled sync with a start date, frequency, cursor, and retry policy.

Later phases may add PDF download for direct preview/evidence, outgoing documents, e-Arsiv, and richer status workflows.

### Product Boundary

QNB is a document source adapter, not an accounting decision engine.

The QNB adapter can provide source evidence:
- Which client connection was used.
- Which QNB sync run imported the document.
- External UUID or invoice identity.
- QNB-side status at the time of listing or status query.
- Raw provider response reference where safe to retain.

Fisora still owns:
- XML parsing.
- Canonical invoice interpretation.
- Direction checks.
- Counterparty matching.
- Account suggestion.
- Draft generation.
- Review gating.
- Export readiness.

### Credential Scope

QNB credentials are client-specific.

Each taxpayer/client has its own QNB connection. One client's QNB account must never be reused for another client's sync. The accountant or office can manage the connection, but the stored credential belongs to that client scope.

The frontend must never receive the stored password or secret value after save. API responses may expose only:
- Connection status.
- Masked username or account label.
- Last successful test time.
- Last failure code/message.
- Whether manual sync is enabled.

### Connection Test Gate

Manual sync is disabled unless the QNB connection test passes.

Connection status values:
- `missing`: no connection has been configured.
- `active`: last connection test passed.
- `auth_failed`: QNB rejected the credential.
- `connection_failed`: QNB endpoint/network/SOAP failure.
- `disabled`: accountant manually disabled the connection.

If the connection is not `active`, the portal sync button is disabled and the latest safe error summary is shown.

### Manual Sync UX

Phase 1 adds a minimal portal action:

```text
QNB'den gelen e-Faturalari al
  start_date
  end_date
```

The active client context supplies `client_id`.

The result summary shows:
- Listed count.
- Downloaded count.
- Skipped duplicate count.
- Status-updated count.
- Failed count.
- Safe error summary if present.

The manual portal action calls a backend endpoint that delegates to the same sync service Phase 2 scheduling will use.

Proposed endpoint shape:

```text
POST /qnb/connections/{client_id}/sync-incoming-invoices
```

### Duplicate Identity

Date range is only a search window. Duplicate detection is identity/hash based.

Detection order:
1. QNB external UUID / UBL UUID.
2. `invoice_no + issue_date + supplier_tax_id + payable_total`.
3. UBL XML SHA-256 hash.

If a listed QNB invoice is already present for the same client, Phase 1 does not create a new document. It records the duplicate skip in the sync run. If the QNB status differs from the stored status, that belongs to Phase 1.5 status reconciliation.

### Storage and Document Import

Downloaded UBL XML enters Fisora as a normal stored document.

Required uploaded document metadata:
- `source_provider = qnb_esolutions`
- `source_direction = incoming_efatura`
- `source_external_uuid`
- `source_invoice_no`
- `source_issue_date`
- `source_supplier_tax_id`
- `source_payable_total`
- `source_sync_run_id`
- `source_qnb_status`
- `source_content_sha256`
- `document_type = einvoice_xml`
- `intake_category = purchase_invoice` as a source hint

`intake_category` remains only a hint. If XML content indicates a different accounting direction, existing content-wins direction conflict behavior should apply and surface review evidence.

### Review and Export Behavior

QNB import does not bypass review or export gates.

After import:
1. The XML parser reads the UBL.
2. Fisora builds the invoice and draft result.
3. Risk flags and review reasons are calculated by the existing workflow.
4. Export readiness remains controlled by Fisora's existing deterministic checks and accountant review.

If canonical invoice lines are missing or invalid, the document must be marked insufficient for automation rather than inferred from supplier title alone.

### Phase 1.5 Status Reconciliation

Cancellation, rejection, and provider status changes are handled in a separate status sync layer.

The status layer does not delete or silently mutate documents. It records external state and raises review evidence.

Proposed status payload:

```text
qnb_document_status
  client_id
  document_ref
  external_uuid
  invoice_no
  source_direction = incoming_efatura
  qnb_status = received | accepted | rejected | cancelled | unknown
  status_checked_at
  status_source = qnb_status_query
  raw_payload_ref
```

Behavior:
- If the document has not been processed, it may be held or moved to `review_required`.
- If a draft exists but is not approved, add a QNB status review flag.
- If the accountant already approved the draft, do not auto-reverse it. Show "QNB status changed" in review/history.
- If the document was already included in an export package, generate review evidence for a separate correction decision. Do not auto-delete or auto-reverse.

### Phase 2 Scheduled Sync

Scheduled sync is per client.

Policy fields:

```text
qnb_sync_policy
  client_id
  enabled
  start_from_date
  frequency
  preferred_time
  direction = incoming_efatura
  last_success_at
  last_checked_until
  max_documents_per_run
```

The scheduler uses the same adapter and sync service as manual sync. It lists documents from the configured start/cursor window, deduplicates by identity/hash, downloads new UBL XML files, stores them, and queues processing jobs.

### Security

Credential values must not be stored in workspace document payloads, pipeline events, or frontend state.

Allowed logs/events:
- Client id.
- Connection id.
- Sync run id.
- Provider name.
- Safe status code.
- External document UUID/invoice number where needed for audit.

Disallowed logs/events:
- Passwords.
- SOAP session tokens.
- Raw auth request/response.
- Full credential payloads.

### Adapter Boundary

The QNB adapter should expose narrow operations:

```text
test_connection(connection) -> ConnectionTestResult
list_incoming_invoices(connection, date_range, cursor) -> list[QnbInvoiceSummary]
download_incoming_invoice_ubl(connection, invoice_ref) -> DownloadedQnbDocument
get_invoice_status(connection, invoice_ref) -> QnbInvoiceStatus
```

Phase 1 uses:
- `test_connection`
- `list_incoming_invoices`
- `download_incoming_invoice_ubl`

Phase 1.5 uses:
- `get_invoice_status`

The rest of the system should depend on Fisora's internal sync service, not directly on SOAP implementation details.

### Implementation Notes

Likely backend units:
- QNB connection persistence for per-client credentials and safe public payloads.
- QNB SOAP adapter with a fake/test implementation for unit tests.
- QNB sync service that converts provider results into Fisora uploaded documents and processing jobs.
- API routes for connection save/test and manual sync.
- Pipeline event recording for connection test, sync start, duplicate skip, download stored, processing queued, and sync completion.

Likely frontend units:
- Minimal client settings QNB connection card.
- Manual sync action in the client/document context.
- Result summary rendering.
- Disabled sync state when connection is not active.

### Acceptance Criteria

Phase 1 is complete when:
- A client-specific QNB connection can be saved and tested.
- Manual sync is disabled until the connection status is active.
- A date-range manual sync can list incoming e-Fatura records through the QNB adapter.
- A new incoming e-Fatura UBL is downloaded once and stored as `einvoice_xml`.
- Duplicate runs skip the same invoice without creating a second document.
- Fisora creates `uploaded_document` and `processing_job` records for the downloaded XML.
- Existing XML preview renders the document.
- Existing XML parser/review workflow produces the same kind of review/export result as a manually uploaded UBL.
- Sync and pipeline events show QNB source evidence without exposing credentials.

### Open Implementation Checks

Before implementation, verify the exact QNB SOAP method names, request fields, response fields, test endpoint, production endpoint, and status values from the current QNB API documentation or sandbox credentials.

The current design intentionally does not depend on exact SOAP method names. The adapter boundary isolates those details.
