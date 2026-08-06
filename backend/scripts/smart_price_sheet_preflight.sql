-- READ ONLY. Run before the migration; this script never changes data.
begin transaction read only;

select version_num as current_alembic_revision from alembic_version;

select table_name
from information_schema.tables
where table_schema = current_schema()
  and table_name in (
    'product_supplier_assessments',
    'product_supplier_assessment_audits',
    'product_purchase_policies',
    'product_purchase_policy_audits',
    'purchase_policy_deviations',
    'smart_price_sheet_previews'
  );

select
  (select count(*) from products) as products,
  (select count(*) from fornitori) as suppliers,
  (select count(*) from listino_master) as price_versions,
  (select count(*) from utenti) as users,
  (select count(*) from location) as locations;

select sku_interno, count(*) as active_versions
from listino_master
where data_scadenza is null
group by fornitore_id, sku_interno, supplier_product_alias_id
having count(*) > 1;

rollback;
