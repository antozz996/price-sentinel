\set ON_ERROR_STOP on
\if :{?apply_cleanup}
\else
  \set apply_cleanup false
\endif

begin;
set local lock_timeout = '5s';
set local statement_timeout = '2min';

do $cleanup_guard$
declare
  product_count integer;
  navas_alias_count integer;
  orphan_list_count integer;
begin
  select count(*) into product_count from public.products;
  select count(*) into navas_alias_count
  from public.supplier_product_aliases
  where supplier_id = 7
    and source = 'supplier_list_bootstrap'
    and status = 'approved';
  select count(*) into orphan_list_count
  from public.listino_master lm
  where lm.supplier_product_alias_id is null
    and not exists (
      select 1 from public.products p where p.sku_interno = lm.sku_interno
    );

  if product_count <> 155 then
    raise exception 'STOP: expected 155 canonical products, found %', product_count;
  end if;
  if navas_alias_count <> 155 then
    raise exception 'STOP: expected 155 approved Navas bootstrap aliases, found %', navas_alias_count;
  end if;
  if orphan_list_count <> 1211 then
    raise exception 'STOP: expected 1211 orphan list rows, found %', orphan_list_count;
  end if;
end
$cleanup_guard$;

create temporary table cleanup_results (
  operation text primary key,
  affected_rows integer not null
) on commit drop;

with changed as (
  update public.products
  set volume_ml = case id
        when 347 then 1500
        when 360 then 330
        when 361 then 330
      end,
      updated_at = now()
  where (id, canonical_name, volume_ml) in (
    (347, 'ACQUA LETE 1,50 CL X 6 BT', 15),
    (360, 'BIRRA HEINEKEN 0.33 CL X 24 BT', 3),
    (361, 'BIRRA NASTRO AZZ. 0.33 CL X 24 BT', 3)
  )
  returning 1
)
insert into cleanup_results
values ('product_volume_corrections', (select count(*) from changed));

with changed as (
  update public.supplier_product_aliases
  set volume_ml = case id
        when 133 then 1500
        when 146 then 330
        when 147 then 330
      end,
      updated_at = now()
  where (id, product_id, volume_ml) in (
    (133, 347, 15),
    (146, 360, 3),
    (147, 361, 3)
  )
  returning 1
)
insert into cleanup_results
values ('alias_volume_corrections', (select count(*) from changed));

with changed as (
  update public.supplier_product_aliases
  set pack_qty = 6,
      updated_at = now()
  where id = 201
    and product_id = 415
    and pack_qty = 1
    and raw_description = 'GRAN CUVE'' TERRA SERENA MILLESIMATO EXTRA DRY 75 CL X 6'
  returning 1
)
insert into cleanup_results
values ('supplier_pack_corrections', (select count(*) from changed));

-- Preserve every historical row. Only expire rows that cannot resolve to the
-- current canonical catalog and would otherwise appear as an active price.
with changed as (
  update public.listino_master lm
  set data_scadenza = current_date - 1
  where lm.supplier_product_alias_id is null
    and (lm.data_scadenza is null or lm.data_scadenza >= current_date)
    and not exists (
      select 1 from public.products p where p.sku_interno = lm.sku_interno
    )
  returning 1
)
insert into cleanup_results
values ('orphan_list_rows_expired', (select count(*) from changed));

table cleanup_results;

select
  count(*) as orphan_list_rows,
  count(*) filter (
    where data_scadenza is null or data_scadenza >= current_date
  ) as active_orphan_list_rows
from public.listino_master lm
where lm.supplier_product_alias_id is null
  and not exists (
    select 1 from public.products p where p.sku_interno = lm.sku_interno
  );

\if :apply_cleanup
  commit;
\else
  rollback;
\endif
