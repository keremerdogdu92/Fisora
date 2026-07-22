-- Durable accountant-reference corpus, immutable reference outcomes and
-- confirmed rule snapshots. These tables are outside ordinary pilot reset.

create table protected_corpora (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    corpus_key text not null,
    version integer not null check (version > 0),
    status text not null check (status in ('draft', 'frozen', 'archived')),
    target_purchase_count integer not null default 35 check (target_purchase_count >= 0),
    target_sales_count integer not null default 15 check (target_sales_count >= 0),
    created_by text not null,
    frozen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, corpus_key, version)
);

create table protected_corpus_items (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid references taxpayers(id) on delete set null,
    corpus_id uuid not null references protected_corpora(id),
    document_id uuid references documents(id) on delete set null,
    source_file_id uuid references source_files(id) on delete set null,
    client_id text not null,
    document_ref text not null,
    source_ref text not null,
    source_sha256 text not null check (length(source_sha256) = 64),
    protected_storage_path text not null,
    direction text not null check (direction in ('purchase', 'sale')),
    status text not null check (status in ('candidate', 'reference_ready')),
    source_snapshot jsonb not null,
    canonical_snapshot jsonb not null default '{}',
    chart_snapshot jsonb not null default '{}',
    current_reference_version integer not null default 0 check (current_reference_version >= 0),
    created_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (corpus_id, source_sha256)
);

create table reference_outcome_versions (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    corpus_item_id uuid not null references protected_corpus_items(id),
    version integer not null check (version > 0),
    source_review_decision_id uuid references review_decisions(id) on delete set null,
    source_journal_revision_id uuid references journal_revisions(id) on delete set null,
    quality_label text not null check (quality_label in ('unchanged', 'minor', 'material', 'unusable')),
    proposal_snapshot jsonb not null,
    accountant_final_decision jsonb not null,
    journal_snapshot jsonb not null,
    allocation_snapshot jsonb not null,
    provenance jsonb not null,
    reviewer text not null,
    reason text not null default '',
    is_authoritative boolean not null default true,
    created_at timestamptz not null default now(),
    unique (corpus_item_id, version)
);

create table protected_rule_versions (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid references taxpayers(id) on delete set null,
    corpus_item_id uuid not null references protected_corpus_items(id),
    reference_version integer not null,
    rule_key text not null,
    version integer not null check (version > 0),
    status text not null check (status in ('active', 'paused', 'archived', 'detached')),
    scope_snapshot jsonb not null,
    rule_snapshot jsonb not null,
    confirmed_by text not null,
    created_at timestamptz not null default now(),
    unique (tenant_id, rule_key, version),
    foreign key (corpus_item_id, reference_version)
        references reference_outcome_versions(corpus_item_id, version)
);

create index idx_protected_corpora_tenant_status
    on protected_corpora(tenant_id, status, created_at);
create index idx_protected_corpus_items_tenant_corpus
    on protected_corpus_items(tenant_id, corpus_id, direction, status);
create index idx_protected_corpus_items_document
    on protected_corpus_items(tenant_id, taxpayer_id, client_id, document_ref, document_id)
    where document_id is not null;
create index idx_reference_outcome_versions_item
    on reference_outcome_versions(tenant_id, corpus_item_id, version desc);
create index idx_protected_rule_versions_scope
    on protected_rule_versions(tenant_id, taxpayer_id, status, rule_key);
