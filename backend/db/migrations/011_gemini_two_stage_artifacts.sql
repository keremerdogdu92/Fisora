-- Immutable linked Gemini direct-PDF and accounting artifact revisions.

create or replace function document_ai_artifact_contains_secret_key(payload jsonb)
returns boolean
language plpgsql
immutable
as $$
declare
    key_name text;
    nested_value jsonb;
    normalized_key text;
begin
    if payload is null then
        return false;
    end if;
    if jsonb_typeof(payload) = 'object' then
        for key_name, nested_value in select key, value from jsonb_each(payload)
        loop
            normalized_key := regexp_replace(lower(key_name), '[^a-z0-9]', '', 'g');
            if normalized_key = any(array[
                'accesstoken', 'apikey', 'authorization', 'clientsecret',
                'credential', 'credentials', 'headers', 'password',
                'refreshtoken', 'secret', 'token', 'xgoogapikey'
            ]) then
                return true;
            end if;
            if document_ai_artifact_contains_secret_key(nested_value) then
                return true;
            end if;
        end loop;
    elsif jsonb_typeof(payload) = 'array' then
        for nested_value in select value from jsonb_array_elements(payload)
        loop
            if document_ai_artifact_contains_secret_key(nested_value) then
                return true;
            end if;
        end loop;
    end if;
    return false;
end;
$$;

create table if not exists document_ai_artifacts (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    document_id uuid not null references documents(id),
    source_file_id uuid not null references source_files(id),
    artifact_kind text not null
        check (artifact_kind in (
            'provider_receipt',
            'canonical_invoice_form',
            'accounting_input_projection',
            'accounting_proposal'
        )),
    revision_no integer not null check (revision_no > 0),
    parent_artifact_id uuid references document_ai_artifacts(id),
    retry_of_artifact_id uuid references document_ai_artifacts(id),
    provider_receipt_artifact_id uuid references document_ai_artifacts(id),
    component_receipt_artifact_ids uuid[] not null default '{}'::uuid[],
    expanded_from_receipt_id uuid references document_ai_artifacts(id),
    stage text not null,
    status text not null,
    provider text,
    model_alias text,
    resolved_model text,
    elapsed_ms integer check (elapsed_ms is null or elapsed_ms >= 0),
    http_status integer check (http_status is null or http_status between 100 and 599),
    started_at timestamptz,
    finished_at timestamptz,
    token_usage jsonb not null default '{}',
    error_metadata jsonb not null default '{}',
    metadata jsonb not null default '{}',
    source_file_sha256 text not null,
    content_storage_path text,
    content_sha256 text,
    request_storage_path text,
    request_sha256 text,
    response_storage_path text,
    response_sha256 text,
    prompt_version text,
    schema_version text,
    mapper_version text,
    pipeline_version text not null default '',
    created_at timestamptz not null default now(),
    unique (tenant_id, taxpayer_id, document_id, artifact_kind, revision_no),
    check (
        (artifact_kind = 'provider_receipt'
         and parent_artifact_id is null
         and provider_receipt_artifact_id is null
         and cardinality(component_receipt_artifact_ids) = 0
         and content_storage_path is null
         and content_sha256 is null
         and request_storage_path is not null
         and request_sha256 is not null
         and response_storage_path is not null
         and response_sha256 is not null)
        or
        (artifact_kind <> 'provider_receipt'
         and parent_artifact_id is not null
         and retry_of_artifact_id is null
         and content_storage_path is not null
         and content_sha256 is not null
         and request_storage_path is null
         and request_sha256 is null
         and response_storage_path is null
         and response_sha256 is null)
    ),
    check (retry_of_artifact_id is null or artifact_kind = 'provider_receipt'),
    check (expanded_from_receipt_id is null or artifact_kind = 'provider_receipt'),
    check (expanded_from_receipt_id is null or stage = 'accounting_selection'),
    check (artifact_kind = 'provider_receipt' or (
        http_status is null and started_at is null and finished_at is null
    )),
    check ((started_at is null and finished_at is null) or (
        started_at is not null and finished_at is not null and finished_at >= started_at
    )),
    check (artifact_kind <> 'accounting_proposal' or provider_receipt_artifact_id is not null),
    check (artifact_kind = 'accounting_proposal' or cardinality(component_receipt_artifact_ids) = 0),
    check (cardinality(component_receipt_artifact_ids) = 0
        or provider_receipt_artifact_id = any(component_receipt_artifact_ids)),
    check (artifact_kind <> 'accounting_input_projection' or provider_receipt_artifact_id is null),
    check (not document_ai_artifact_contains_secret_key(metadata)),
    check (not document_ai_artifact_contains_secret_key(error_metadata)),
    check (not document_ai_artifact_contains_secret_key(token_usage))
);

alter table document_ai_artifacts
    add column if not exists component_receipt_artifact_ids uuid[] not null default '{}'::uuid[];

create index if not exists idx_document_ai_artifacts_lineage
    on document_ai_artifacts(tenant_id, taxpayer_id, document_id, created_at);
create index if not exists idx_document_ai_artifacts_source
    on document_ai_artifacts(tenant_id, taxpayer_id, source_file_id);

create or replace function enforce_document_ai_artifact_scope_and_lineage()
returns trigger
language plpgsql
as $$
declare
    linked_kind text;
    linked_stage text;
    linked_status text;
    component_receipt_id uuid;
begin
    if not exists (
        select 1 from documents d
        where d.id = new.document_id
          and d.tenant_id = new.tenant_id
          and d.taxpayer_id = new.taxpayer_id
    ) then
        raise exception 'document_ai_artifact_scope_mismatch: document';
    end if;

    if not exists (
        select 1 from source_files s
        where s.id = new.source_file_id
          and s.tenant_id = new.tenant_id
          and s.taxpayer_id = new.taxpayer_id
          and s.sha256 = new.source_file_sha256
    ) then
        raise exception 'document_ai_artifact_scope_mismatch: source';
    end if;

    if not exists (
        select 1 from document_sources ds
        where ds.document_id = new.document_id
          and ds.source_file_id = new.source_file_id
          and ds.tenant_id = new.tenant_id
          and ds.taxpayer_id = new.taxpayer_id
    ) then
        raise exception 'document_ai_artifact_scope_mismatch: document_source';
    end if;

    if new.parent_artifact_id is not null then
        select artifact_kind, stage, status into linked_kind, linked_stage, linked_status
        from document_ai_artifacts
        where id = new.parent_artifact_id
          and tenant_id = new.tenant_id
          and taxpayer_id = new.taxpayer_id
          and document_id = new.document_id
          and source_file_id = new.source_file_id
          and source_file_sha256 = new.source_file_sha256;

        if not found then
            raise exception 'document_ai_artifact_scope_mismatch: parent';
        end if;
        if (new.artifact_kind = 'canonical_invoice_form' and linked_kind <> 'provider_receipt')
           or (new.artifact_kind = 'accounting_input_projection' and linked_kind <> 'canonical_invoice_form')
           or (new.artifact_kind = 'accounting_proposal' and linked_kind <> 'accounting_input_projection') then
            raise exception 'document_ai_artifact_lineage_kind_mismatch';
        end if;
        if new.artifact_kind = 'canonical_invoice_form'
           and linked_stage <> 'document_extraction' then
            raise exception 'canonical_parent_receipt_must_be_document_extraction';
        end if;
        if new.artifact_kind = 'canonical_invoice_form'
           and linked_status <> 'successful' then
            raise exception 'canonical_parent_receipt_must_be_successful';
        end if;
    elsif new.artifact_kind <> 'provider_receipt' then
        raise exception 'document_ai_artifact_lineage_parent_required';
    end if;

    if new.provider_receipt_artifact_id is not null then
        select stage, status into linked_stage, linked_status
        from document_ai_artifacts
        where id = new.provider_receipt_artifact_id
          and artifact_kind = 'provider_receipt'
          and tenant_id = new.tenant_id
          and taxpayer_id = new.taxpayer_id
          and document_id = new.document_id
          and source_file_id = new.source_file_id
          and source_file_sha256 = new.source_file_sha256;
        if not found then
            raise exception 'document_ai_artifact_scope_mismatch: provider_receipt';
        end if;
        if new.artifact_kind = 'canonical_invoice_form'
           and new.provider_receipt_artifact_id <> new.parent_artifact_id then
            raise exception 'canonical_provider_receipt_must_match_parent';
        end if;
        if new.artifact_kind = 'canonical_invoice_form'
           and linked_stage <> 'document_extraction' then
            raise exception 'canonical_provider_receipt_must_be_document_extraction';
        end if;
        if new.artifact_kind = 'canonical_invoice_form'
           and linked_status <> 'successful' then
            raise exception 'canonical_provider_receipt_must_be_successful';
        end if;
        if new.artifact_kind = 'accounting_proposal'
           and linked_stage <> 'accounting_selection' then
            raise exception 'accounting_proposal_receipt_must_be_accounting_selection';
        end if;
        if new.artifact_kind = 'accounting_proposal'
           and linked_status <> 'successful' then
            raise exception 'accounting_proposal_receipt_must_be_successful';
        end if;
        if new.artifact_kind = 'accounting_input_projection' then
            raise exception 'accounting_projection_has_no_provider_receipt_call';
        end if;
    elsif new.artifact_kind = 'accounting_proposal' then
        raise exception 'accounting_proposal_provider_receipt_required';
    end if;

    if cardinality(new.component_receipt_artifact_ids) > 0 then
        if new.artifact_kind <> 'accounting_proposal' then
            raise exception 'component_receipts_only_valid_for_accounting_proposal';
        end if;
        if not (new.provider_receipt_artifact_id = any(new.component_receipt_artifact_ids)) then
            raise exception 'primary_provider_receipt_must_be_a_component_receipt';
        end if;
        if cardinality(new.component_receipt_artifact_ids) <>
           cardinality(array(select distinct unnest(new.component_receipt_artifact_ids))) then
            raise exception 'component_receipt_lineage_cannot_contain_duplicates';
        end if;
        foreach component_receipt_id in array new.component_receipt_artifact_ids
        loop
            perform 1
            from document_ai_artifacts
            where id = component_receipt_id
              and artifact_kind = 'provider_receipt'
              and stage = 'accounting_selection'
              and status = 'successful'
              and tenant_id = new.tenant_id
              and taxpayer_id = new.taxpayer_id
              and document_id = new.document_id
              and source_file_id = new.source_file_id
              and source_file_sha256 = new.source_file_sha256;
            if not found then
                raise exception 'document_ai_artifact_scope_mismatch: component_receipt';
            end if;
        end loop;
    end if;

    if new.retry_of_artifact_id is not null then
        perform 1
        from document_ai_artifacts
        where id = new.retry_of_artifact_id
          and artifact_kind = 'provider_receipt'
          and tenant_id = new.tenant_id
          and taxpayer_id = new.taxpayer_id
          and document_id = new.document_id
          and source_file_id = new.source_file_id
          and source_file_sha256 = new.source_file_sha256;
        if not found then
            raise exception 'document_ai_artifact_scope_mismatch: retry';
        end if;
    end if;

    if new.expanded_from_receipt_id is not null then
        select stage, status into linked_stage, linked_status
        from document_ai_artifacts
        where id = new.expanded_from_receipt_id
          and artifact_kind = 'provider_receipt'
          and tenant_id = new.tenant_id
          and taxpayer_id = new.taxpayer_id
          and document_id = new.document_id
          and source_file_id = new.source_file_id
          and source_file_sha256 = new.source_file_sha256;
        if not found then
            raise exception 'document_ai_artifact_scope_mismatch: expanded_from';
        end if;
        if linked_stage <> 'accounting_selection' then
            raise exception 'expanded_from_receipt_must_be_accounting_selection';
        end if;
        if linked_status <> 'successful' then
            raise exception 'expanded_from_receipt_must_be_successful';
        end if;
    end if;

    return new;
end;
$$;

drop trigger if exists trg_document_ai_artifact_scope_lineage on document_ai_artifacts;
create trigger trg_document_ai_artifact_scope_lineage
before insert on document_ai_artifacts
for each row execute function enforce_document_ai_artifact_scope_and_lineage();

create or replace function prevent_document_ai_artifact_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'document_ai_artifacts are append-only';
end;
$$;

drop trigger if exists trg_document_ai_artifact_append_only on document_ai_artifacts;
create trigger trg_document_ai_artifact_append_only
before update or delete on document_ai_artifacts
for each row execute function prevent_document_ai_artifact_mutation();
