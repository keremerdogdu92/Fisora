# Fisora UI cleanup handoff — 2026-09-05

## Scope

This change set is intentionally isolated from the active invoice-pipeline worktree.
Branch: `ui-cleanup-20260905`
Base commit: `7288e91`

The accounting workbench layout and journal interaction model are **not** redesigned in this change set.
Only the original-document preview error/diagnostic path inside the review screen was changed.

## Completed UI cleanup

- Settings no longer presents developer-facing Auth / Store / Production / reset-test-data controls.
- Active sessions show account context and logout instead of a redundant login form.
- QNB is presented as a normal integration section.
- Operations is reduced to accountant-facing document flow, system status and office summary.
- Outputs no longer presents the unimplemented Zirve direct-send flow as a working action.
- Zirve is explicitly marked as planned; current output path remains XLSX / CSV oriented.
- Duplicate new-client action and duplicate client-portal action were removed.
- New-client onboarding no longer looks like a blocking wizard; tax certificate, chart plan and optional portal access remain clear sections.
- Quick upload has one file-selection surface and explicitly shows the upload period.

## Original document preview diagnostics

The old visible `Failed to fetch / Mock belge çizimi kapalı` presentation is removed.
Preview failures now run a lightweight authenticated pipeline probe to separate:

- session / client access failure (`401/403`),
- missing stored document (`404`),
- document record accessible but binary transfer failed,
- backend/network unreachable.

Raw transport details are kept behind `Önizleme tanısı`; the main error copy is user-facing.
No accounting decision, journal generation, reader or source-line behavior was changed.

## Verification

- `git diff --check`: clean.
- Next production build: successful.
- Frontend test suite: `207/207` passed.
- 1440px visual smoke: Outputs, Clients, Client Detail, New Client, Uploads, Operations and Settings.
- No horizontal overflow observed in the smoke run.

## Explicitly deferred: Çalışma Masası

Do not fold further workbench/journal UX changes into this cleanup commit.
The accounting workbench is a sensitive surface and will be reviewed separately with Kerem before implementation.
Topics to discuss separately include journal-row density, warnings/chips, source evidence layout, action hierarchy and workspace proportions.
Existing queue/source/journal structure, zoom, magnifier, source highlighting, fullscreen and keyboard interactions remain out of scope here.
