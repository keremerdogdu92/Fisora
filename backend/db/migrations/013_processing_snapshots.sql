-- File: backend/db/migrations/013_processing_snapshots.sql
-- Summary: Adds attempt-scoped progressive invoice processing snapshots without changing final document results.

alter table processing_jobs
    add column if not exists processing_snapshot jsonb not null default '{}'::jsonb;
