-- Safety gate before `alembic downgrade ls_s8_onboarding`.
-- It deliberately aborts when business/audit data exists.
do $$
declare
  populated_tables text;
begin
  select string_agg(table_name, ', ' order by table_name)
    into populated_tables
  from (
    select 'product_supplier_assessments' table_name
      where exists (select 1 from product_supplier_assessments limit 1)
    union all select 'product_supplier_assessment_audits'
      where exists (select 1 from product_supplier_assessment_audits limit 1)
    union all select 'product_purchase_policies'
      where exists (select 1 from product_purchase_policies limit 1)
    union all select 'product_purchase_policy_audits'
      where exists (select 1 from product_purchase_policy_audits limit 1)
    union all select 'purchase_policy_deviations'
      where exists (select 1 from purchase_policy_deviations limit 1)
    union all select 'smart_price_sheet_previews'
      where exists (select 1 from smart_price_sheet_previews limit 1)
  ) populated;

  if populated_tables is not null then
    raise exception
      'Rollback refused: export and explicitly approve removal of data in %',
      populated_tables;
  end if;
end $$;
