-- File: backend/db/migrations/014_document_source_snapshots.sql
-- Summary: Adds immutable, tenant-scoped structural source snapshot persistence for the frozen HTML Source Reader.

create table if not exists document_source_snapshots (
    id uuid primary key,
    tenant_id uuid not null references tenants(id) on delete cascade,
    taxpayer_id uuid not null references taxpayers(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    source_file_id uuid not null references source_files(id) on delete cascade,
    source_file_sha256 text not null,
    snapshot_version text not null,
    reader_version text not null,
    parser_kind text not null,
    snapshot_sha256 text not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    unique (
        tenant_id, taxpayer_id, document_id, source_file_id,
        snapshot_version, reader_version
    ),
    check (source_file_sha256 ~ '^[0-9a-f]{64}$'),
    check (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    check (jsonb_typeof(payload) = 'object')
);

create index if not exists idx_document_source_snapshots_document
on document_source_snapshots(tenant_id, taxpayer_id, document_id, created_at desc);

create or replace function enforce_document_source_snapshot_scope()
returns trigger
language plpgsql
as $$
begin
    if not exists (
        select 1 from documents d
        where d.id = new.document_id
          and d.tenant_id = new.tenant_id
          and d.taxpayer_id = new.taxpayer_id
    ) then
        raise exception 'document_source_snapshot_scope_mismatch: document';
    end if;

    if not exists (
        select 1 from source_files s
        where s.id = new.source_file_id
          and s.tenant_id = new.tenant_id
          and s.taxpayer_id = new.taxpayer_id
          and s.sha256 = new.source_file_sha256
    ) then
        raise exception 'document_source_snapshot_scope_mismatch: source_file';
    end if;

    if not exists (
        select 1 from document_sources ds
        where ds.document_id = new.document_id
          and ds.source_file_id = new.source_file_id
          and ds.tenant_id = new.tenant_id
          and ds.taxpayer_id = new.taxpayer_id
    ) then
        raise exception 'document_source_snapshot_scope_mismatch: document_source';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_document_source_snapshot_scope on document_source_snapshots;
create trigger trg_document_source_snapshot_scope
before insert on document_source_snapshots
for each row execute function enforce_document_source_snapshot_scope();

create or replace function prevent_document_source_snapshot_update()
returns trigger
language plpgsql
as $$
begin
    raise exception 'document_source_snapshot_is_immutable';
end;
$$;

drop trigger if exists trg_document_source_snapshot_immutable on document_source_snapshots;
create trigger trg_document_source_snapshot_immutable
before update on document_source_snapshots
for each row execute function prevent_document_source_snapshot_update();
