-- Typed accounting-period ownership and grouped source-retention lifecycle.

alter table documents add column if not exists accounting_period date;
alter table source_files add column if not exists accounting_period date;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'documents'::regclass
          and conname = 'ck_documents_accounting_period_month_start'
    ) then
        alter table documents add constraint ck_documents_accounting_period_month_start
            check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'source_files'::regclass
          and conname = 'ck_source_files_accounting_period_month_start'
    ) then
        alter table source_files add constraint ck_source_files_accounting_period_month_start
            check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date);
    end if;
end
$$;

create table if not exists retention_batches (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    accounting_period date not null,
    preparation_on date not null,
    warning_on date not null,
    delete_on date not null,
    status text not null default 'scheduled'
        check (status in ('scheduled', 'warning_open', 'deleting', 'resolved')),
    opened_at timestamptz,
    read_at timestamptz,
    resolved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, accounting_period),
    check (accounting_period = date_trunc('month', accounting_period)::date),
    check (preparation_on < warning_on and warning_on <= delete_on)
);

create table if not exists retention_batch_sources (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    retention_batch_id uuid not null references retention_batches(id) on delete cascade,
    source_file_id uuid not null references source_files(id),
    created_at timestamptz not null default now(),
    unique (retention_batch_id, source_file_id)
);

create table if not exists retention_scheduler_state (
    tenant_id uuid primary key references tenants(id),
    next_run_at timestamptz not null default now(),
    claimed_by text,
    claim_expires_at timestamptz,
    updated_at timestamptz not null default now()
);

create index if not exists idx_retention_batches_due
    on retention_batches(tenant_id, status, warning_on, delete_on);
