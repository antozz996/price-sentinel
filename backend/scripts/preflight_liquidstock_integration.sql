\set ON_ERROR_STOP on

begin transaction read only;

with required_tables(table_name) as (
  values
    ('liquidstock_integration_events'),
    ('liquidstock_supplier_orders'),
    ('liquidstock_supplier_order_items')
),
checks(check_name, observed_count, expected_count) as (
  select 'required_tables_missing', count(*)::bigint, 0::bigint
  from required_tables
  where to_regclass('public.' || table_name) is null
  union all
  select 'event_identity_unique_missing',
    case when exists (
      select 1
      from pg_catalog.pg_constraint
      where conrelid='public.liquidstock_integration_events'::regclass
        and conname='uq_liquidstock_integration_events_source_event'
        and contype='u'
    ) then 0::bigint else 1::bigint end,
    0::bigint
  union all
  select 'supplier_order_identity_unique_missing',
    case when exists (
      select 1
      from pg_catalog.pg_constraint
      where conrelid='public.liquidstock_supplier_orders'::regclass
        and conname='uq_liquidstock_supplier_orders_external_id'
        and contype='u'
    ) then 0::bigint else 1::bigint end,
    0::bigint
  union all
  select 'duplicate_event_identity', count(*)::bigint, 0::bigint
  from (
    select source,external_event_id
    from public.liquidstock_integration_events
    group by source,external_event_id
    having count(*)>1
  ) duplicates
  union all
  select 'duplicate_supplier_order_identity', count(*)::bigint, 0::bigint
  from (
    select liquidstock_supplier_order_id
    from public.liquidstock_supplier_orders
    group by liquidstock_supplier_order_id
    having count(*)>1
  ) duplicates
  union all
  select 'supplier_order_item_orphans', count(*)::bigint, 0::bigint
  from public.liquidstock_supplier_order_items item
  left join public.liquidstock_supplier_orders supplier_order
    on supplier_order.id=item.supplier_order_id
  where supplier_order.id is null
  union all
  select 'supplier_mapping_orphans', count(*)::bigint, 0::bigint
  from public.liquidstock_supplier_orders supplier_order
  left join public.fornitori supplier on supplier.id=supplier_order.supplier_id
  where supplier_order.supplier_id is not null and supplier.id is null
  union all
  select 'product_mapping_orphans', count(*)::bigint, 0::bigint
  from public.liquidstock_supplier_order_items item
  left join public.products product on product.id=item.product_id
  where item.product_id is not null and product.id is null
  union all
  select 'invalid_payload_hash', count(*)::bigint, 0::bigint
  from public.liquidstock_integration_events
  where payload_hash !~ '^[0-9a-f]{64}$'
)
select check_name,observed_count,expected_count,
  case when observed_count=expected_count then 'PASS' else 'STOP' end as status
from checks
order by check_name;

rollback;
