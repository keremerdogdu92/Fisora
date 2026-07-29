create table if not exists journal_edit_leases (
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    journal_entry_id uuid not null references journal_entries(id),
    owner_actor_id text not null,
    owner_role text not null,
    acquired_at timestamptz not null,
    last_user_activity_at timestamptz not null,
    expires_at timestamptz not null,
    takeover_reason text,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, journal_entry_id),
    check (expires_at = last_user_activity_at + interval '5 minutes')
);

create table if not exists journal_working_drafts (
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    journal_entry_id uuid not null references journal_entries(id),
    base_revision_no integer not null,
    candidate_revision_no integer not null,
    revision_role text not null default 'candidate',
    current_export_status text not null,
    draft_snapshot jsonb not null default '{}',
    saved_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, journal_entry_id),
    check (revision_role = 'candidate'),
    check (candidate_revision_no = base_revision_no + 1)
);

create index if not exists idx_journal_edit_leases_expiry
    on journal_edit_leases(tenant_id, expires_at);
create index if not exists idx_journal_working_drafts_updated
    on journal_working_drafts(tenant_id, taxpayer_id, updated_at desc);
