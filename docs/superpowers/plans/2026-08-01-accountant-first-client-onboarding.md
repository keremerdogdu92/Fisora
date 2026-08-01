# Accountant-first Client Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove portal password from accountant onboarding while preserving optional client invitations.

**Architecture:** `buildClientOnboardingPackagePayload` must emit an empty `portal_users` list when no portal identity is supplied. The wizard validates identity and chart readiness only; after creation it exposes the existing invitation action.

**Tech Stack:** FastAPI/Pydantic, Python unittest, React/TypeScript, Node test runner.

## Global Constraints

- Never enable password bootstrap in production.
- Chart accounts must come only from the client's imported chart plan.
- Portal access is not an accounting-processing gate.

### Task 1: Portal-optional payload

**Files:** `frontend/app/upload-api.js`, `frontend/app/upload-api.test.cjs`

- [ ] RED: add a test calling `buildClientOnboardingPackagePayload` without `portalUserId` and assert `portal_users` equals `[]`.
- [ ] Run `node --test frontend/app/upload-api.test.cjs`; it must fail because the current builder creates `<client_id>-user`.
- [ ] GREEN: only append the `client_user` object when `portalUserId` is non-empty.
- [ ] Re-run the focused test.

### Task 2: Accountant-first wizard

**Files:** `frontend/app/portal-client-actions.ts`, `frontend/app/portal-clients-view.tsx`, nearest frontend action test.

- [ ] RED: add a test proving a chart-ready client with no portal identity/password invokes `createClientOnboardingPackage`.
- [ ] Run the focused test; it must fail with the present portal-password validation.
- [ ] GREEN: remove the portal identity/password validation and mandatory third step. Render portal invitation as an optional post-create action.
- [ ] Re-run the focused test and `node --test frontend/app/*.test.cjs`.

### Task 3: Backend access proof

**Files:** `backend/tests/test_document_upload_api.py`, verify `backend/app/services/workspace_service.py`.

- [ ] RED: add an authenticated onboarding API test with `portal_users: []`; assert the actor has access and chart accounts persist.
- [ ] Run the focused unittest.
- [ ] GREEN: keep the existing empty-list loop and accountant grant unless the test reveals an authorization gap.
- [ ] Run `python -m unittest discover -s backend/tests`.

### Task 4: Release and live acceptance

- [ ] Run frontend build and `git diff --check`.
- [ ] After user-owned release, create Rana with the visual tax certificate and 916 imported accounts while password bootstrap remains disabled.
- [ ] Upload 25 purchase and 32 sales UBL files, then inspect identity/direction, balance, review reasons, and export status without exporting.
