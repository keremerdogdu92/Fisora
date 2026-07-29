-- Durable AI provider outage episodes and bounded processing-job retries.

create table if not exists ai_outage_episodes (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    task_kind text not null,
    status text not null
        check (status in ('open', 'recovered')),
    opened_at timestamptz not null,
    last_failure_at timestamptz not null,
    recovered_at timestamptz,
    failed_provider_categories jsonb not null default '[]',
    affected_document_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table processing_jobs add column if not exists next_attempt_at timestamptz;
alter table processing_jobs add column if not exists retry_step integer not null default 0;
alter table processing_jobs add column if not exists outage_episode_id uuid references ai_outage_episodes(id);

create index if not exists idx_processing_jobs_due_retry
    on processing_jobs(tenant_id, status, next_attempt_at)
    where status = 'retry_wait';
create unique index if not exists uq_ai_outage_episode_open_task
    on ai_outage_episodes(tenant_id, task_kind)
    where status = 'open';
