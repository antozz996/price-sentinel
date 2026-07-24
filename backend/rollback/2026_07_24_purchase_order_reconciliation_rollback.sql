\set ON_ERROR_STOP on
begin;
do $$
begin
  if to_regclass('public.purchase_order_reconciliations') is not null
     and exists (select 1 from public.purchase_order_reconciliations) then
    raise exception 'rollback_blocked: operational reconciliations exist';
  end if;
end $$;
drop table if exists public.purchase_order_reconciliation_anomalies;
drop table if exists public.purchase_order_reconciliation_items;
drop table if exists public.purchase_order_reconciliations;
drop table if exists public.liquidstock_venue_mappings;
commit;
