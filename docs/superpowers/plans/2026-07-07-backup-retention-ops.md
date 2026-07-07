# Backup Retention Ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a concrete manual/semi-automated backup plan and change document retention from silent expiry deletion to accountant-approved delete or 90-day extension.

**Implementation status:** Completed on 2026-07-07. Backup env/copy controls, retention preview/action API, workflow-store behavior, frontend helpers, operations panel, and ops runbook were implemented. Local `bash -n` was skipped because this Windows environment has no `/bin/bash`; run it on the server before deploy.

**Architecture:** Keep existing database/document backup script, but make the backup target explicit and add an off-machine copy step. For retention, split expired-document detection from destructive deletion: a dry-run returns a downloadable/inspectable list, the accountant confirms delete or extend, and only confirmed delete removes files.

**Tech Stack:** Shell backup script, FastAPI document routes, existing workflow stores, document upload domain, production readiness checks, React portal ops UI, Python unittest and Node tests.

---

## File Map

- Modify `deploy/backup/backup.sh`: add manifest, restore note, and optional copy target env.
- Modify `deploy/production.env.example`: document backup interval, local dir, and off-machine target.
- Modify `backend/app/domain/document_uploads.py`: add retention action model for `delete` and `extend_90_days`.
- Modify `backend/app/persistence/workflow_store.py`: implement retention preview and explicit retention action for file-backed store.
- Modify `backend/app/persistence/postgres_workflow_store.py`: implement the same behavior for Postgres store.
- Modify `backend/app/services/document_service.py`: expose preview and action methods with operation events.
- Modify `backend/app/api/phase0_schemas.py`: add retention preview/action payloads.
- Modify `backend/app/api/phase0_routes_upload_processing.py`: add `/store/document-retention/preview` and `/store/document-retention/action`.
- Modify `backend/tests/test_document_uploads.py` and `backend/tests/test_workflow_store.py`: cover retention preview, delete confirmation, and extension.
- Modify `frontend/app/upload-api.js`: add retention preview/action calls.
- Modify `frontend/app/portal-client-actions.ts` or the ops panel owning retention UI: show expired list and delete/extend actions.
- Modify `docs/production-ops-runbook.md`: document backup and retention operator steps.

## Task 1: Backup Script Off-Machine Copy

**Files:**
- Modify `deploy/backup/backup.sh`
- Modify `deploy/production.env.example`

- [ ] **Step 1: Add backup script comments and env contract**

At the top of `backup.sh`, document:

```sh
# Required: DATABASE_URL
# Optional:
#   FISORA_BACKUP_DIR=/opt/fisora/data/backups
#   FISORA_DOCUMENT_STORAGE_PATH=/opt/fisora/data/documents
#   FISORA_BACKUP_COPY_DIR=/mnt/fisora-backups
#   FISORA_BACKUP_KEEP_DAYS=14
```

- [ ] **Step 2: Add configurable keep days**

Replace hardcoded `14` with:

```sh
BACKUP_KEEP_DAYS="${FISORA_BACKUP_KEEP_DAYS:-14}"
```

and use:

```sh
find "$BACKUP_DIR" -type f -name 'postgres-*.sql' -mtime +"$BACKUP_KEEP_DAYS" -delete
find "$BACKUP_DIR" -type f -name 'documents-*.manifest.tsv' -mtime +"$BACKUP_KEEP_DAYS" -delete
```

- [ ] **Step 3: Add optional copy target**

After writing the SQL and document manifest, add:

```sh
if [ -n "${FISORA_BACKUP_COPY_DIR:-}" ]; then
  mkdir -p "$FISORA_BACKUP_COPY_DIR"
  cp "$BACKUP_DIR/postgres-$stamp.sql" "$FISORA_BACKUP_COPY_DIR/postgres-$stamp.sql"
  if [ -f "$BACKUP_DIR/documents-$stamp.manifest.tsv" ]; then
    cp "$BACKUP_DIR/documents-$stamp.manifest.tsv" "$FISORA_BACKUP_COPY_DIR/documents-$stamp.manifest.tsv"
  fi
fi
```

- [ ] **Step 4: Run shell syntax check if available**

Run:

```powershell
bash -n deploy/backup/backup.sh
```

If `bash` is not available on Windows, run this on the server before deploy and record that local syntax check was skipped.

## Task 2: Retention Preview Domain

**Files:**
- Modify `backend/app/domain/document_uploads.py`
- Test `backend/tests/test_document_uploads.py`

- [ ] **Step 1: Write failing domain tests**

```python
def test_retention_decision_expired_does_not_imply_auto_delete_without_action(self) -> None:
    from datetime import datetime, timezone
    from app.domain.document_uploads import retention_decision

    document = {
        "document_id": "doc-1",
        "expires_at": "2026-01-01T00:00:00+00:00",
        "deleted_at": "",
        "storage_status": "stored",
    }

    decision = retention_decision(document, now=datetime(2026, 4, 1, tzinfo=timezone.utc))

    self.assertEqual(decision.storage_status, "expired")
    self.assertTrue(decision.should_delete)
    self.assertEqual(decision.reason, "retention_expired")
```

This test documents the existing low-level decision. The next store tests will assert that route preview does not delete files.

- [ ] **Step 2: Add extension helper test**

```python
def test_extend_retention_deadline_adds_90_days_from_current_expiry(self) -> None:
    from app.domain.document_uploads import extend_retention_deadline

    self.assertEqual(
        extend_retention_deadline("2026-01-01T00:00:00+00:00", days=90),
        "2026-04-01T00:00:00+00:00",
    )
```

- [ ] **Step 3: Implement extension helper**

```python
def extend_retention_deadline(expires_at: str, *, days: int = 90) -> str:
    if days <= 0:
        raise ValueError("days must be positive")
    parsed = datetime.fromisoformat(expires_at)
    return isoformat(parsed + timedelta(days=days))
```

- [ ] **Step 4: Run domain tests**

Run:

```powershell
python -m unittest backend.tests.test_document_uploads
```

Expected: document upload domain tests pass.

## Task 3: Store Preview and Explicit Action

**Files:**
- Modify `backend/app/persistence/workflow_store.py`
- Modify `backend/app/persistence/postgres_workflow_store.py`
- Test `backend/tests/test_workflow_store.py`

- [ ] **Step 1: Write failing preview test**

```python
def test_document_retention_preview_does_not_delete_expired_file(self) -> None:
    store = WorkflowStore(self.path)
    # Use existing test helper style in this file to insert an uploaded document with past expires_at.
    preview = store.preview_document_retention()

    self.assertEqual(preview["expired_count"], 1)
    self.assertEqual(preview["deleted_count"], 0)
    self.assertTrue(self.document_path.exists())
```

- [ ] **Step 2: Write failing extension action test**

```python
def test_document_retention_action_extends_expired_document(self) -> None:
    store = WorkflowStore(self.path)
    result = store.apply_document_retention_action(document_refs=["doc-1"], action="extend_90_days")

    self.assertEqual(result["extended_count"], 1)
    document = store.get_uploaded_document("client-1", "doc-1")
    self.assertEqual(document["storage_status"], "stored")
    self.assertEqual(document["deleted_at"], "")
```

- [ ] **Step 3: Implement `preview_document_retention`**

Return a compact list:

```python
{
    "checked_count": checked_count,
    "expiring_count": expiring_count,
    "expired_count": expired_count,
    "documents": expired_or_expiring_documents,
}
```

Do not unlink files in preview.

- [ ] **Step 4: Implement `apply_document_retention_action`**

For `action == "delete"`, mark selected docs deleted and unlink files when `delete_files=True`.

For `action == "extend_90_days"`, update `expires_at`, `download_available_until`, `storage_status`, and `updated_at`; do not move or delete files.

- [ ] **Step 5: Mirror behavior in Postgres store**

Implement identical public method names and return payload keys in `postgres_workflow_store.py`.

- [ ] **Step 6: Run workflow store tests**

Run:

```powershell
python -m unittest backend.tests.test_workflow_store
```

Expected: both file store and existing store behavior pass.

## Task 4: API and Service Layer

**Files:**
- Modify `backend/app/api/phase0_schemas.py`
- Modify `backend/app/api/phase0_routes_upload_processing.py`
- Modify `backend/app/services/document_service.py`
- Test `backend/tests/test_document_upload_api.py`

- [ ] **Step 1: Add schemas**

```python
class DocumentRetentionActionPayload(BaseModel):
    document_refs: list[str] = Field(default_factory=list)
    action: str
    delete_files: bool = True
```

- [ ] **Step 2: Add routes**

```python
@router.post("/store/document-retention/preview")
def store_document_retention_preview() -> dict[str, object]:
    return get_document_service().store_document_retention_preview()


@router.post("/store/document-retention/action")
def store_document_retention_action(payload: DocumentRetentionActionPayload) -> dict[str, object]:
    return get_document_service().store_document_retention_action(
        document_refs=payload.document_refs,
        action=payload.action,
        delete_files=payload.delete_files,
    )
```

- [ ] **Step 3: Keep old run endpoint non-destructive by default**

Change `/store/document-retention/run` or its UI usage so it is used for preview unless an explicit action is supplied. If keeping the old endpoint for compatibility, document that it is an operator-only destructive endpoint.

- [ ] **Step 4: Run document upload API tests**

Run:

```powershell
python -m unittest backend.tests.test_document_upload_api
```

Expected: retention preview/action routes pass.

## Task 5: Frontend Ops Controls

**Files:**
- Modify `frontend/app/upload-api.js`
- Modify `frontend/app/portal-client-actions.ts` or the retention UI owner
- Test `frontend/app/upload-api.test.cjs`

- [ ] **Step 1: Add upload API tests**

```javascript
test("previewDocumentRetention posts preview route", async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ expired_count: 1, documents: [] });
  };

  await api.previewDocumentRetention({ apiBaseUrl: "https://example.test", sessionToken: "s" });

  assert.equal(calls[0].url, "https://example.test/store/document-retention/preview");
});
```

- [ ] **Step 2: Implement API helpers**

Add:

```javascript
export async function previewDocumentRetention({ apiBaseUrl, sessionToken = "", userHeader = "" } = {}) { ... }
export async function applyDocumentRetentionAction({ apiBaseUrl, documentRefs, action, deleteFiles = true, sessionToken = "", userHeader = "" } = {}) { ... }
```

- [ ] **Step 3: Add UI actions**

Show two explicit actions for expired documents:
  - `Sil ve onayla`
  - `90 gun uzat`

Do not show client download as an option.

- [ ] **Step 4: Run frontend tests and build**

Run:

```powershell
node --test frontend/app/upload-api.test.cjs
cd frontend
npm.cmd run build
```

Expected: tests pass and build completes.

## Task 6: Runbook and Final Verification

**Files:**
- Modify `docs/production-ops-runbook.md`
- Modify `deploy/production.env.example`

- [ ] Add operator steps:
  - Run backup once before deploy.
  - Confirm SQL backup exists.
  - Confirm document manifest exists.
  - Confirm off-machine copy exists when `FISORA_BACKUP_COPY_DIR` is configured.
  - Preview expired documents.
  - Download or inspect the expired list.
  - Choose delete or 90-day extension.

- [ ] Run final checks:

```powershell
python -m unittest backend.tests.test_document_uploads backend.tests.test_workflow_store backend.tests.test_document_upload_api
node --test frontend/app/upload-api.test.cjs
git diff --check
```

- [ ] Acceptance:
  - Backup can be run manually and copied off-machine.
  - Expired documents are not silently deleted by the UI flow.
  - Accountant has delete or 90-day extension choice.
  - Client still has preview-only access by default.
