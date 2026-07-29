---
name: fisero-diagnose-live
description: Diagnose Fisero live bugs, stale or surprising UI state, timeouts, missing uploads, broken review or learning behavior, provider failures, and pipeline discrepancies by tracing the real frontend, API, service, persistence, workflow_records, logs, and rendered-result path. Use when the user asks neden boyle oldu, canlida ne oldu, veri neden gorunmuyor, neden yavas, or requests evidence-backed runtime truth.
---

# Diagnose Fisero Live Behavior

## Define the symptom

Record the user-visible symptom, actor, tenant/client, document or operation
identity, expected behavior, observed behavior, environment, and time window.
Do not mutate production while establishing cause.

## Trace the real path

Follow:

`UI state -> frontend mapper/request -> API route -> service/workflow ->
persistence -> workflow_records -> worker/provider/logs -> response -> render`

Use the codebase knowledge graph for code definitions, callers, and data flow.
Use text search for error literals, config, SQL, logs, and documentation.

Start live pipeline, review, upload, and learning evidence in
`workflow_records`. Compare normalized tables only after establishing the event
history. Correlate by stable identifiers and timestamps; do not rely on display
names alone.

## Separate failure classes

Distinguish:

- frontend rendering or stale-query behavior;
- API/auth/tenant boundary failure;
- service validation or workflow decision;
- queued, leased, retried, completed, or failed worker state;
- provider latency, quota, schema, or credential failure;
- persistence/projection drift;
- expected safety gating such as `review_required`;
- successful processing with an unusable accounting result.

## Prove the conclusion

Give the smallest evidence chain that explains the symptom. State what is
confirmed, what remains inferred, and what evidence would falsify the diagnosis.

Do not implement a fix when the user asked only for diagnosis. If a fix is
requested, propose the narrowest correction, affected paths, regression risks,
and verification before editing.

Read [references/runtime-proof.md](references/runtime-proof.md) for the evidence
sequence and handoff format.
