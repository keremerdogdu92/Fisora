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
    accounting_period date,
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
    ,constraint ck_documents_accounting_period_month_start
        check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date)
);

create table if not exists source_files (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    taxpayer_id uuid not null references taxpayers(id),
    accounting_period date,
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
    unique (tenant_id, taxpayer_id, sha256),
    constraint ck_source_files_accounting_period_month_start
        check (accounting_period is null or accounting_period = date_trunc('month', accounting_period)::date)
);

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

create table if not exists ai_outage_episodes (
    id uuid primary key,
    tenant_id uuid not null references tenants(id),
    task_kind text not null,
    status text not null
        check (status in ('open', 'recovered')),
    opened_at timestamptz not null,
    last_failure_at timestamptz not null,
    recovered_at timestamptz,
    failed_provider_categories jsonb not null default '[]',
    affected_document_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
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
    next_attempt_at timestamptz,
    retry_step integer not null default 0,
    outage_episode_id uuid references ai_outage_episodes(id),
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
alter table processing_jobs add column if not exists processing_snapshot jsonb not null default '{}'::jsonb;
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
    rule_key text,
    version integer not null default 1,
    status text not null default 'draft'
        check (status in ('draft', 'active', 'paused', 'archived')),
    schema_version text not null default 'v1',
    scope_snapshot jsonb not null default '{}',
    rule_snapshot jsonb not null default '{}',
    activation_event_id uuid,
    confirmed_by text,
    confirmed_at timestamptz,
    supersedes_rule_id uuid references learning_rules(id),
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
create unique index if not exists uq_learning_rules_key_version
    on learning_rules(tenant_id, rule_key, version)
    where rule_key is not null;
create index if not exists idx_learning_rules_active_scope
    on learning_rules(tenant_id, taxpayer_id, status, scope, rule_key)
    where status = 'active';
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
create index if not exists idx_processing_jobs_due_retry
    on processing_jobs(tenant_id, status, next_attempt_at)
    where status = 'retry_wait';
create index if not exists idx_journal_revisions_document on journal_revisions(tenant_id, taxpayer_id, document_id, revision_no desc);
create index if not exists idx_journal_edit_leases_expiry
    on journal_edit_leases(tenant_id, expires_at);
create index if not exists idx_journal_working_drafts_updated
    on journal_working_drafts(tenant_id, taxpayer_id, updated_at desc);
create index if not exists idx_workflow_events_document on workflow_events(tenant_id, taxpayer_id, document_id, created_at);

