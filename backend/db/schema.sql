-- Phase 0 relational model draft. This is not a production migration.

create table tenants (
    id uuid primary key,
    name text not null,
    tax_number text,
    status text not null default 'active',
    retention_policy_months integer,
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
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
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

