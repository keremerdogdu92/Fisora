-- Phase 0 relational model draft. This is not a production migration.

create table tenants (
    id uuid primary key,
    name text not null,
    tax_number text,
    status text not null default 'active',
    retention_policy_months integer,
    document_retention_days integer not null default 90,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table taxpayers (
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

create table portal_users (
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

create table portal_user_client_access (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    user_id uuid not null references portal_users(id),
    taxpayer_id uuid not null references taxpayers(id),
    access_role text not null default 'client_user',
    created_at timestamptz not null default now(),
    unique (tenant_id, user_id, taxpayer_id)
);

create table chart_account_imports (
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

create table chart_accounts (
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
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, normalized_account_code)
);

create table documents (
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

create table workflow_records (
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

create table invoice_lines (
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
    created_at timestamptz not null default now()
);

create table counterparties (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    chart_account_id uuid references chart_accounts(id),
    normalized_account_code text not null,
    display_name text not null,
    tax_id text,
    counterparty_type text not null,
    confidence_score numeric(5, 2),
    match_reason text,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table journal_entries (
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

create table journal_entry_lines (
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
    tax_rate numeric(5, 4),
    document_reference text,
    created_at timestamptz not null default now(),
    check (not (debit_amount > 0 and credit_amount > 0))
);

create table export_batches (
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

create table review_decisions (
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

create table learning_rules (
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

create index idx_taxpayers_tenant_status on taxpayers(tenant_id, status);
create index idx_portal_users_tenant_key on portal_users(tenant_id, external_user_key);
create index idx_portal_user_client_access_taxpayer on portal_user_client_access(tenant_id, taxpayer_id);
create index idx_chart_accounts_taxpayer_code on chart_accounts(tenant_id, taxpayer_id, normalized_account_code);
create index idx_chart_accounts_counterparty_tax on chart_accounts(tenant_id, taxpayer_id, tax_id)
    where tax_id is not null and is_detail_account = true;
create index idx_documents_taxpayer_status on documents(tenant_id, taxpayer_id, status);
create index idx_documents_retention on documents(tenant_id, storage_status, expires_at)
    where storage_status in ('stored', 'expiring');
create index idx_workflow_records_lookup on workflow_records(tenant_id, client_id, record_type, created_at);
create index idx_workflow_records_type_key on workflow_records(tenant_id, record_type, record_key);
create index idx_journal_entries_taxpayer_export on journal_entries(tenant_id, taxpayer_id, export_status);
create index idx_review_decisions_taxpayer_created on review_decisions(tenant_id, taxpayer_id, created_at desc);
create index idx_learning_rules_scope on learning_rules(tenant_id, taxpayer_id, scope, automation_candidate);
create index idx_export_batches_taxpayer_status on export_batches(tenant_id, taxpayer_id, status);

