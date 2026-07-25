create table if not exists document_identities (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    identity_kind text not null,
    identity_value text not null,
    source_channel text not null,
    state text not null default 'committed',
    claimed_at timestamptz not null default now(),
    committed_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, identity_kind, identity_value)
);

create table if not exists provider_document_links (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    provider text not null,
    connection_ref text not null default '',
    external_identity text not null,
    current_status text not null default 'unknown',
    current_status_event_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, provider, external_identity)
);

create table if not exists external_status_events (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    provider_link_id uuid not null references provider_document_links(id),
    event_key text not null,
    external_status text not null,
    observed_at timestamptz not null,
    provider_payload jsonb not null default '{}',
    created_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, provider_link_id, event_key)
);

alter table provider_document_links
    drop constraint if exists provider_document_links_current_status_event_id_fkey;
alter table provider_document_links
    add constraint provider_document_links_current_status_event_id_fkey
    foreign key (current_status_event_id) references external_status_events(id);

create table if not exists document_safety_holds (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    hold_code text not null,
    trigger_event_id uuid not null references external_status_events(id),
    created_at timestamptz not null default now(),
    resolved_at timestamptz,
    resolved_by text,
    resolution_note text
);

create index if not exists idx_document_identities_document
    on document_identities(tenant_id, taxpayer_id, document_id);
create index if not exists idx_provider_document_links_document
    on provider_document_links(tenant_id, taxpayer_id, document_id);
create index if not exists idx_external_status_events_document
    on external_status_events(tenant_id, taxpayer_id, document_id, observed_at desc);
create unique index if not exists uq_document_safety_holds_active
    on document_safety_holds(tenant_id, taxpayer_id, document_id, hold_code)
    where resolved_at is null;
