alter table chart_accounts add column if not exists iban text;
alter table counterparties add column if not exists iban text;

create index if not exists idx_chart_accounts_counterparty_iban
    on chart_accounts(tenant_id, taxpayer_id, iban)
    where iban is not null and is_detail_account = true;
