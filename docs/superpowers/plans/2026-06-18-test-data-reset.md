# Test Data Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled way to clear all pilot taxpayer/test data while preserving the accountant login.

**Architecture:** Put the destructive behavior behind a store-level `reset_test_data` method, expose it through an accountant/admin-only backend route, and call it from `/portal/ayarlar` with explicit confirmation. The reset preserves accountant/admin portal users and their credentials while deleting client records, client portal users, sessions/tokens, workflow records, and generated/uploaded files.

**Tech Stack:** FastAPI backend, JSON/Postgres workflow stores, Next.js/React portal UI, Node and unittest test suites.

---

### Task 1: Store Reset Behavior

**Files:**
- Modify: `backend/tests/test_workflow_store.py`
- Modify: `backend/app/persistence/workflow_store.py`
- Modify: `backend/app/persistence/postgres_workflow_store.py`

- [ ] Write failing tests showing accountant auth is preserved and client data/files are removed.
- [ ] Implement `reset_test_data(document_storage_path, export_path)` for JSON and Postgres stores.
- [ ] Re-run the targeted workflow store tests until green.

### Task 2: Backend Route

**Files:**
- Modify: `backend/tests/test_auth_policy.py`
- Modify: `backend/app/api/phase0_schemas.py`
- Modify: `backend/app/api/phase0_routes_auth.py`

- [ ] Write failing tests for an accountant-only reset route.
- [ ] Add request schema with confirmation text and delete-files flag.
- [ ] Implement `POST /phase0/store/admin/test-reset`.
- [ ] Re-run backend auth tests until green.

### Task 3: Frontend Settings Control

**Files:**
- Modify: `frontend/app/upload-api.js`
- Modify: `frontend/app/upload-api.test.cjs`
- Modify: `frontend/app/portal-settings-view.tsx`
- Modify: `frontend/app/portal-app.tsx`
- Modify: `frontend/app/styles.css`

- [ ] Write failing frontend test for the reset API helper.
- [ ] Add a settings danger panel visible to accountant sessions.
- [ ] Require the `TEMIZLE` confirmation text before enabling reset.
- [ ] Refresh backend pilot data after reset.

### Task 4: Verify and Deploy

**Files:**
- Commit all touched files.

- [ ] Run `python -m unittest discover -s backend/tests`.
- [ ] Run `node --test frontend/app/*.test.cjs`.
- [ ] Run `npm.cmd run build` from `frontend/`.
- [ ] Run `git diff --check`.
- [ ] Push `main`, fast-forward server, run `check`, `deploy`, and `smoke`.
- [ ] Call the live reset endpoint once and verify clients/routes/readiness.
