-- Versioned, explicitly activated learning-rule lifecycle.

alter table learning_rules add column if not exists rule_key text;
alter table learning_rules add column if not exists version integer not null default 1;
alter table learning_rules add column if not exists status text not null default 'draft';
alter table learning_rules add column if not exists schema_version text not null default 'v1';
alter table learning_rules add column if not exists scope_snapshot jsonb not null default '{}';
alter table learning_rules add column if not exists rule_snapshot jsonb not null default '{}';
alter table learning_rules add column if not exists activation_event_id uuid;
alter table learning_rules add column if not exists confirmed_by text;
alter table learning_rules add column if not exists confirmed_at timestamptz;
alter table learning_rules add column if not exists supersedes_rule_id uuid references learning_rules(id);

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'learning_rules'::regclass
          and conname = 'ck_learning_rules_status'
    ) then
        alter table learning_rules add constraint ck_learning_rules_status
            check (status in ('draft', 'active', 'paused', 'archived'));
    end if;
end
$$;

create unique index if not exists uq_learning_rules_key_version
    on learning_rules(tenant_id, rule_key, version)
    where rule_key is not null;
create index if not exists idx_learning_rules_active_scope
    on learning_rules(tenant_id, taxpayer_id, status, scope, rule_key)
    where status = 'active';
