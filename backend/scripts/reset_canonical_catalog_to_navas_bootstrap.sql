\set ON_ERROR_STOP on

begin;

create temporary table keep_products on commit drop as
select distinct alias.product_id
from supplier_product_aliases alias
where alias.supplier_id = 7
  and alias.source = 'supplier_list_bootstrap'
  and alias.status = 'approved';

do $$
begin
    if (select count(*) from keep_products) <> 155 then
        raise exception 'STOP: expected 155 Navas bootstrap products, found %',
            (select count(*) from keep_products);
    end if;

    if (select count(*) from products) <> 430 then
        raise exception 'STOP: expected 430 products before cleanup, found %',
            (select count(*) from products);
    end if;

    if exists (
        select 1
        from purchase_order_reconciliation_items item
        where item.product_id is not null
          and item.product_id not in (select product_id from keep_products)
    ) then
        raise exception 'STOP: an old product is referenced by a reconciliation item';
    end if;

    if (select count(*)
        from liquidstock_supplier_order_items item
        where item.product_id is not null
          and item.product_id not in (select product_id from keep_products)) <> 1 then
        raise exception 'STOP: expected exactly one old order-item product reference';
    end if;

    if not exists (
        select 1 from liquidstock_supplier_order_items
        where id = 5 and product_id = 59 and product_name_snapshot = 'Acqua Electa 1L PET'
    ) then
        raise exception 'STOP: expected Acqua Electa historical order reference not found';
    end if;

    if not exists (
        select 1
        from products product
        join supplier_product_aliases alias on alias.product_id = product.id
        where product.id = 340
          and product.canonical_name = 'ACQUA ELECTA 1 LT PET X 12'
          and alias.supplier_id = 7
          and alias.source = 'supplier_list_bootstrap'
    ) then
        raise exception 'STOP: replacement Acqua Electa bootstrap product not found';
    end if;
end $$;

update liquidstock_supplier_order_items
set product_id = 340
where id = 5
  and product_id = 59
  and product_name_snapshot = 'Acqua Electa 1L PET';

do $$
begin
    if not exists (
        select 1 from liquidstock_supplier_order_items
        where id = 5 and product_id = 340 and product_name_snapshot = 'Acqua Electa 1L PET'
    ) then
        raise exception 'STOP: Acqua Electa order-item remap was not applied';
    end if;
end $$;

with deleted as (
    delete from listino_master listino
    where exists (
        select 1
        from products product
        where product.id not in (select product_id from keep_products)
          and product.sku_interno = listino.sku_interno
    )
    returning id
)
select 'OLD_LISTINO_DELETED|' || count(*) from deleted;

with deleted as (
    delete from products product
    where product.id not in (select product_id from keep_products)
    returning id
)
select 'OLD_PRODUCTS_DELETED|' || count(*) from deleted;

do $$
begin
    if (select count(*) from products) <> 155 then
        raise exception 'STOP: final catalog contains % products instead of 155',
            (select count(*) from products);
    end if;

    if exists (
        select 1 from products
        where id not in (select product_id from keep_products)
    ) then
        raise exception 'STOP: a non-bootstrap product remains';
    end if;

    if (select count(*)
        from supplier_product_aliases
        where supplier_id = 7
          and source = 'supplier_list_bootstrap'
          and status = 'approved') <> 155 then
        raise exception 'STOP: Navas bootstrap aliases are not 155';
    end if;

    if (select count(*)
        from listino_master listino
        join supplier_product_aliases alias on alias.id = listino.supplier_product_alias_id
        where alias.supplier_id = 7
          and alias.source = 'supplier_list_bootstrap'
          and listino.data_scadenza is null) <> 155 then
        raise exception 'STOP: active Navas bootstrap prices are not 155';
    end if;
end $$;

select 'FINAL_PRODUCTS|' || count(*) from products;
select 'FINAL_ALIASES|' || count(*) from supplier_product_aliases;
select 'FINAL_ACTIVE_PRICES|' || count(*) from listino_master where data_scadenza is null;
select 'FINAL_PENDING_CANDIDATES|' || count(*) from match_candidates where status = 'pending';

commit;
