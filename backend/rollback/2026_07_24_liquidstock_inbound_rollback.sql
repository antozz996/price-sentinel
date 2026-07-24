\set ON_ERROR_STOP on

begin;

do $$
begin
  if to_regclass('public.liquidstock_integration_events') is not null
     and exists (select 1 from public.liquidstock_integration_events) then
    raise exception
      'rollback_blocked: liquidstock integration events exist';
  end if;
  if to_regclass('public.liquidstock_supplier_orders') is not null
     and exists (select 1 from public.liquidstock_supplier_orders) then
    raise exception
      'rollback_blocked: liquidstock supplier orders exist';
  end if;
end $$;

drop table if exists public.liquidstock_supplier_order_items;
drop table if exists public.liquidstock_supplier_orders;
drop table if exists public.liquidstock_integration_events;

commit;
