-- Phase 0 relational model reference. Versioned migrations expand this schema.

create table if not exists tenants (
    id uuid primary key,
    name text not null,
    tax_number text,
    status text not null default 'active',
    retention_policy_months integer,
    document_retention_days integer not null default 90,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists taxpayers (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    display_name text not null,
    legal_name text,
    tax_number text,
    tax_office text,
    activity_description text,
    nace_code text,
    workplace_addresses jsonb not null default '[]',
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists portal_users (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    external_user_key text not null,
    display_name text not null,
    role text not null,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, external_user_key)
);

create table if not exists portal_user_client_access (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    user_id uuid not null references portal_users(id),
    taxpayer_id uuid not null references taxpayers(id),
    access_role text not null default 'client_user',
    created_at timestamptz not null default now(),
    unique (tenant_id, user_id, taxpayer_id)
);

create table if not exists chart_account_imports (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    source_filename text not null,
    status text not null,
    imported_count integer not null default 0,
    skipped_count integer not null default 0,
    error_count integer not null default 0,
    created_at timestamptz not null default now()
);

create table if not exists chart_accounts (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    import_id uuid references chart_account_imports(id),
    raw_account_code text not null,
    normalized_account_code text not null,
    account_name text not null,
    is_detail_account boolean not null default false,
    tax_id text,
    tax_office text,
    iban text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, normalized_account_code)
);

create table if not exists documents (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    uploaded_by_user_id uuid,
    source_filename text not null,
    stored_filename text,
    storage_path text,
    size_bytes bigint,
    sha256 text,
    document_type text not null,
    status text not null default 'uploaded',
    storage_status text not null default 'stored',
    retention_policy_days integer not null default 90,
    download_available_until timestamptz,
    expires_at timestamptz,
    deleted_at timestamptz,
    parse_notes jsonb not null default '[]',
    risk_flags jsonb not null default '[]',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists source_files (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    source_ref text not null,
    original_filename text not null,
    stored_filename text,
    storage_path text not null,
    storage_backend text not null default 'local',
    media_type text,
    size_bytes bigint not null default 0,
    sha256 text not null,
    status text not null default 'stored',
    retention_policy_days integer not null default 90,
    download_available_until timestamptz,
    expires_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, sha256)
);

create table if not exists document_sources (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    source_file_id uuid not null references source_files(id),
    relationship_type text not null default 'canonical',
    is_canonical boolean not null default false,
    created_at timestamptz not null default now(),
    unique (document_id, source_file_id)
);

create table if not exists workflow_records (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    client_id text not null,
    record_type text not null,
    record_key text not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, client_id, record_type, record_key)
);

create table if not exists invoice_lines (
    id uuid primary key,
    document_id uuid not null references documents(id),
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    line_no integer not null,
    raw_text text not null,
    product_category text,
    product_confidence numeric(5, 2),
    relevance_status text,
    relevance_confidence numeric(5, 2),
    relevance_reason text,
    extraction_version integer not null default 1,
    source_fingerprint text,
    superseded_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists processing_jobs (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    document_ref text not null,
    document_type text not null,
    parser_kind text not null,
    intake_category text not null default '',
    status text not null default 'queued',
    attempt_count integer not null default 0,
    claimed_by text,
    claim_expires_at timestamptz,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, document_ref)
);

create table if not exists processing_attempts (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    processing_job_id uuid not null references processing_jobs(id),
    attempt_no integer not null,
    status text not null,
    worker_id text,
    error_category text,
    error_message text,
    metrics jsonb not null default '{}',
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (processing_job_id, attempt_no)
);

create table if not exists ai_attempts (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    processing_attempt_id uuid references processing_attempts(id),
    provider text not null,
    model text,
    status text not null,
    prompt_version text,
    schema_version text,
    usage_metadata jsonb not null default '{}',
    evidence jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create table if not exists counterparties (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    chart_account_id uuid references chart_accounts(id),
    normalized_account_code text not null,
    display_name text not null,
    tax_id text,
    iban text,
    counterparty_type text not null,
    confidence_score numeric(5, 2),
    match_reason text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists journal_entries (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    entry_date date not null,
    entry_type text not null,
    description text,
    status text not null default 'draft',
    total_debit numeric(18, 2) not null default 0,
    total_credit numeric(18, 2) not null default 0,
    confidence_score numeric(5, 2),
    risk_flags jsonb not null default '[]',
    export_status text not null default 'review_required',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (total_debit = total_credit)
);

create table if not exists journal_entry_lines (
    id uuid primary key,
    journal_entry_id uuid not null references journal_entries(id),
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    line_no integer not null,
    raw_account_code text not null,
    chart_account_id uuid references chart_accounts(id),
    description text,
    debit_amount numeric(18, 2) not null default 0,
    credit_amount numeric(18, 2) not null default 0,
    tax_rate numeric(7, 4),
    document_reference text,
    created_at timestamptz not null default now(),
    check (not (debit_amount > 0 and credit_amount > 0))
);

create table if not exists journal_revisions (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    journal_entry_id uuid not null references journal_entries(id),
    revision_no integer not null,
    base_revision_no integer,
    status text not null,
    total_debit numeric(18, 2) not null,
    total_credit numeric(18, 2) not null,
    is_balanced boolean not null,
    export_status text not null,
    result_snapshot jsonb not null,
    created_by text,
    created_at timestamptz not null default now(),
    approved_by text,
    approved_at timestamptz,
    reopen_reason text,
    unique (journal_entry_id, revision_no),
    check (total_debit = total_credit or status <> 'approved')
);

create table if not exists journal_revision_lines (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    journal_revision_id uuid not null references journal_revisions(id),
    canonical_invoice_line_id uuid references invoice_lines(id) on delete set null,
    line_no integer not null,
    raw_account_code text not null,
    description text,
    debit_amount numeric(18, 2) not null default 0,
    credit_amount numeric(18, 2) not null default 0,
    tax_rate numeric(7, 4),
    allocation_metadata jsonb not null default '{}',
    created_at timestamptz not null default now(),
    unique (journal_revision_id, line_no),
    check (debit_amount >= 0 and credit_amount >= 0),
    check (
        (debit_amount > 0 and credit_amount = 0)
        or (credit_amount > 0 and debit_amount = 0)
    )
);

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

create table if not exists export_batches (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    export_type text not null,
    status text not null,
    output_filename text,
    generated_at timestamptz,
    downloaded_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists review_decisions (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid references documents(id),
    journal_entry_id uuid references journal_entries(id),
    reviewer_user_id uuid,
    action text not null,
    corrected_account_code text,
    corrected_counterparty_code text,
    category text,
    reason text,
    apply_to_similar boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists workflow_events (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid references taxpayers(id),
    document_id uuid references documents(id),
    event_type text not null,
    status text not null,
    actor text,
    details jsonb not null default '{}',
    created_at timestamptz not null default now()
);

create table if not exists export_batch_items (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    export_batch_id uuid not null references export_batches(id),
    journal_revision_id uuid not null references journal_revisions(id),
    created_at timestamptz not null default now(),
    unique (export_batch_id, journal_revision_id)
);

alter table documents add column if not exists source_ref text;
alter table documents add column if not exists invoice_number text;
alter table documents add column if not exists ettn text;
alter table documents add column if not exists invoice_date date;
alter table documents add column if not exists currency text;
alter table documents add column if not exists accounting_direction text;
alter table documents add column if not exists original_invoice_number text;
alter table documents add column if not exists original_invoice_date date;
alter table documents add column if not exists supplier_title text;
alter table documents add column if not exists supplier_tax_id text;
alter table documents add column if not exists customer_title text;
alter table documents add column if not exists customer_tax_id text;
alter table documents add column if not exists net_total numeric(18, 2);
alter table documents add column if not exists vat_total numeric(18, 2);
alter table documents add column if not exists gross_total numeric(18, 2);
alter table documents add column if not exists current_journal_entry_id uuid references journal_entries(id);
alter table documents add column if not exists current_revision_no integer not null default 0;
alter table invoice_lines add column if not exists canonical_line_id text;
alter table invoice_lines add column if not exists source_position text;
alter table invoice_lines add column if not exists original_description text;
alter table invoice_lines add column if not exists quantity numeric(18, 6);
alter table invoice_lines add column if not exists unit_code text;
alter table invoice_lines add column if not exists unit_price numeric(18, 6);
alter table invoice_lines add column if not exists net_amount numeric(18, 2);
alter table invoice_lines add column if not exists vat_rate numeric(7, 4);
alter table invoice_lines add column if not exists tax_amount numeric(18, 2);
alter table invoice_lines add column if not exists gross_amount numeric(18, 2);
alter table invoice_lines add column if not exists evidence jsonb not null default '[]';
alter table journal_entries add column if not exists document_id uuid references documents(id);
alter table journal_entries add column if not exists current_revision_no integer not null default 0;
alter table journal_entries add column if not exists approved_revision_no integer;
alter table journal_entries add column if not exists version integer not null default 0;
alter table processing_jobs add column if not exists current_attempt_id uuid references processing_attempts(id);
alter table review_decisions add column if not exists journal_revision_id uuid references journal_revisions(id);
alter table review_decisions add column if not exists base_revision_no integer;

create table if not exists learning_rules (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid references taxpayers(id),
    source_review_decision_id uuid references review_decisions(id),
    scope text not null,
    action text not null,
    category text,
    corrected_account_code text,
    corrected_counterparty_code text,
    reason text,
    automation_candidate boolean not null default false,
    consistent_approval_count integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_taxpayers_tenant_status on taxpayers(tenant_id, status);
create index if not exists idx_portal_users_tenant_key on portal_users(tenant_id, external_user_key);
create index if not exists idx_portal_user_client_access_taxpayer on portal_user_client_access(tenant_id, taxpayer_id);
create index if not exists idx_chart_accounts_taxpayer_code on chart_accounts(tenant_id, taxpayer_id, normalized_account_code);
create index if not exists idx_chart_accounts_counterparty_tax on chart_accounts(tenant_id, taxpayer_id, tax_id)
    where tax_id is not null and is_detail_account = true;
create index if not exists idx_chart_accounts_counterparty_iban on chart_accounts(tenant_id, taxpayer_id, iban)
    where iban is not null and is_detail_account = true;
create index if not exists idx_documents_taxpayer_status on documents(tenant_id, taxpayer_id, status);
create index if not exists idx_documents_retention on documents(tenant_id, storage_status, expires_at)
    where storage_status in ('stored', 'expiring');
create index if not exists idx_workflow_records_lookup on workflow_records(tenant_id, client_id, record_type, created_at);
create index if not exists idx_workflow_records_type_key on workflow_records(tenant_id, record_type, record_key);
create index if not exists idx_journal_entries_taxpayer_export on journal_entries(tenant_id, taxpayer_id, export_status);
create index if not exists idx_review_decisions_taxpayer_created on review_decisions(tenant_id, taxpayer_id, created_at desc);
create index if not exists idx_learning_rules_scope on learning_rules(tenant_id, taxpayer_id, scope, automation_candidate);
create index if not exists idx_export_batches_taxpayer_status on export_batches(tenant_id, taxpayer_id, status);
create unique index if not exists uq_documents_tenant_taxpayer_source_ref
    on documents(tenant_id, taxpayer_id, source_ref) where source_ref is not null;
create unique index if not exists uq_document_sources_canonical
    on document_sources(document_id) where is_canonical = true;
create unique index if not exists uq_documents_tenant_taxpayer_ettn
    on documents(tenant_id, taxpayer_id, ettn) where ettn is not null and ettn <> '';
drop index if exists uq_invoice_lines_document_canonical;
create unique index if not exists uq_invoice_lines_document_canonical_version
    on invoice_lines(document_id, canonical_line_id, extraction_version)
    where canonical_line_id is not null;
create unique index if not exists uq_journal_entries_document
    on journal_entries(document_id) where document_id is not null;
create index if not exists idx_journal_line_allocations_revision_line
    on journal_line_allocations(journal_revision_line_id);
create index if not exists idx_journal_line_allocations_invoice_line
    on journal_line_allocations(invoice_line_id);
create index if not exists idx_source_files_taxpayer_created on source_files(tenant_id, taxpayer_id, created_at);
create index if not exists idx_processing_jobs_claim on processing_jobs(tenant_id, status, created_at);
create index if not exists idx_journal_revisions_document on journal_revisions(tenant_id, taxpayer_id, document_id, revision_no desc);
create index if not exists idx_workflow_events_document on workflow_events(tenant_id, taxpayer_id, document_id, created_at);

