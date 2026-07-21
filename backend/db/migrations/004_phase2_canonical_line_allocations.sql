-- Phase 2 canonical line identity, immutable extraction lineage and
-- relational source-to-journal allocation.

alter table invoice_lines
    add column if not exists extraction_version integer not null default 1;
alter table invoice_lines
    add column if not exists source_fingerprint text;
alter table invoice_lines
    add column if not exists superseded_at timestamptz;
alter table invoice_lines
    alter column source_position type text using source_position::text;
alter table journal_entry_lines
    alter column tax_rate type numeric(7, 4);
alter table journal_revision_lines
    alter column tax_rate type numeric(7, 4);
alter table processing_jobs
    add column if not exists current_attempt_id uuid references processing_attempts(id);
alter table documents add column if not exists original_invoice_number text;
alter table documents add column if not exists original_invoice_date date;

drop index if exists uq_invoice_lines_document_canonical;
create unique index if not exists uq_invoice_lines_document_canonical_version
    on invoice_lines(document_id, canonical_line_id, extraction_version)
    where canonical_line_id is not null;

create table if not exists journal_line_allocations (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    journal_revision_line_id uuid not null references journal_revision_lines(id),
    invoice_line_id uuid not null references invoice_lines(id),
    allocation_kind text not null,
    allocated_net numeric(18, 2) not null default 0,
    allocated_tax numeric(18, 2) not null default 0,
    allocated_gross numeric(18, 2) not null default 0,
    currency text not null default 'TRY',
    allocation_method text not null,
    evidence jsonb not null default '{}',
    created_at timestamptz not null default now(),
    unique (journal_revision_line_id, invoice_line_id, allocation_kind),
    check (allocation_kind in ('net', 'tax', 'gross', 'special_tax', 'rounding')),
    check (allocated_net >= 0 and allocated_tax >= 0 and allocated_gross >= 0),
    check (allocated_net > 0 or allocated_tax > 0 or allocated_gross > 0)
);

create index if not exists idx_journal_line_allocations_revision_line
    on journal_line_allocations(journal_revision_line_id);
create index if not exists idx_journal_line_allocations_invoice_line
    on journal_line_allocations(invoice_line_id);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'ck_journal_revision_lines_nonnegative'
    ) then
        alter table journal_revision_lines
            add constraint ck_journal_revision_lines_nonnegative
            check (debit_amount >= 0 and credit_amount >= 0) not valid;
    end if;
    if not exists (
        select 1 from pg_constraint where conname = 'ck_journal_revision_lines_one_sided'
    ) then
        alter table journal_revision_lines
            add constraint ck_journal_revision_lines_one_sided
            check (
                (debit_amount > 0 and credit_amount = 0)
                or (credit_amount > 0 and debit_amount = 0)
            ) not valid;
    end if;
end $$;
