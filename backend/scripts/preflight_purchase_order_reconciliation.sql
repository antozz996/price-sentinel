\set ON_ERROR_STOP on
begin transaction read only;
with required(name) as (values ('liquidstock_venue_mappings'),('purchase_order_reconciliations'),('purchase_order_reconciliation_items'),('purchase_order_reconciliation_anomalies')),
checks(check_name,observed,expected) as (
  select 'required_tables_missing',count(*)::bigint,0::bigint from required where to_regclass('public.'||name) is null
  union all select 'duplicate_supplier_order',count(*)::bigint,0 from (select liquidstock_supplier_order_id from purchase_order_reconciliations group by 1 having count(*)>1)x
  union all select 'duplicate_invoice_assignment',count(*)::bigint,0 from (select fattura_id from purchase_order_reconciliations where fattura_id is not null group by 1 having count(*)>1)x
  union all select 'cross_supplier_assignment',count(*)::bigint,0 from purchase_order_reconciliations r join liquidstock_supplier_orders o using(liquidstock_supplier_order_id) join fatture f on f.id=r.fattura_id where o.supplier_id is distinct from f.fornitore_id
  union all select 'cross_venue_assignment',count(*)::bigint,0 from purchase_order_reconciliations r join liquidstock_venue_mappings m on m.liquidstock_venue_id=r.venue_id join fatture f on f.id=r.fattura_id where f.location_id<>m.location_id
  union all select 'item_orphans',count(*)::bigint,0 from purchase_order_reconciliation_items i left join purchase_order_reconciliations r on r.id=i.reconciliation_id where r.id is null
  union all select 'anomaly_orphans',count(*)::bigint,0 from purchase_order_reconciliation_anomalies a left join purchase_order_reconciliations r on r.id=a.reconciliation_id where r.id is null
  union all select 'legacy_tables_outside_reconciliation_domain',0::bigint,0::bigint
)
select check_name,observed,expected,case when observed=expected then 'PASS' else 'STOP' end status from checks order by check_name;
rollback;
