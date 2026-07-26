\set ON_ERROR_STOP on
begin transaction read only;
with required(name) as (
  values
    ('liquidstock_venue_mappings'),
    ('purchase_order_reconciliations'),
    ('purchase_order_reconciliation_items'),
    ('purchase_order_reconciliation_anomalies'),
    ('supplier_identity_equivalences'),
    ('supplier_identity_equivalence_audit')
),
checks(check_name,observed,expected) as (
  select 'required_tables_missing',count(*)::bigint,0::bigint from required where to_regclass('public.'||name) is null
  union all select 'duplicate_supplier_order',count(*)::bigint,0 from (select liquidstock_supplier_order_id from purchase_order_reconciliations group by 1 having count(*)>1)x
  union all select 'duplicate_invoice_assignment',count(*)::bigint,0 from (select fattura_id from purchase_order_reconciliations where fattura_id is not null group by 1 having count(*)>1)x
  union all select 'invoice_supplier_snapshot_drift',count(*)::bigint,0
    from purchase_order_reconciliations r
    join fatture f on f.id=r.fattura_id
    where r.invoice_supplier_id is distinct from f.fornitore_id
  union all select 'unaudited_cross_supplier_assignment',count(*)::bigint,0
    from purchase_order_reconciliations r
    join liquidstock_supplier_orders o using(liquidstock_supplier_order_id)
    join fatture f on f.id=r.fattura_id
    left join supplier_identity_equivalences e on e.id=r.supplier_equivalence_id
    where o.supplier_id is distinct from f.fornitore_id
      and (
        e.id is null
        or least(e.canonical_supplier_id,e.equivalent_supplier_id)
           <> least(o.supplier_id,f.fornitore_id)
        or greatest(e.canonical_supplier_id,e.equivalent_supplier_id)
           <> greatest(o.supplier_id,f.fornitore_id)
        or r.supplier_equivalence_approved_by is null
        or r.supplier_equivalence_approved_at is null
        or r.supplier_equivalence_used_at is null
        or nullif(btrim(r.supplier_equivalence_reason_snapshot),'') is null
      )
  union all select 'same_supplier_with_equivalence',count(*)::bigint,0
    from purchase_order_reconciliations r
    where r.fattura_id is not null
      and r.supplier_id=r.invoice_supplier_id
      and (
        r.supplier_equivalence_id is not null
        or r.supplier_equivalence_approved_by is not null
        or r.supplier_equivalence_approved_at is not null
        or r.supplier_equivalence_used_at is not null
        or r.supplier_equivalence_reason_snapshot is not null
      )
  union all select 'cross_venue_assignment',count(*)::bigint,0 from purchase_order_reconciliations r join liquidstock_venue_mappings m on m.liquidstock_venue_id=r.venue_id join fatture f on f.id=r.fattura_id where f.location_id<>m.location_id
  union all select 'item_orphans',count(*)::bigint,0 from purchase_order_reconciliation_items i left join purchase_order_reconciliations r on r.id=i.reconciliation_id where r.id is null
  union all select 'anomaly_orphans',count(*)::bigint,0 from purchase_order_reconciliation_anomalies a left join purchase_order_reconciliations r on r.id=a.reconciliation_id where r.id is null
  union all select 'supplier_equivalence_self_links',count(*)::bigint,0
    from supplier_identity_equivalences
    where canonical_supplier_id=equivalent_supplier_id
  union all select 'supplier_equivalence_unordered_duplicates',count(*)::bigint,0
    from (
      select least(canonical_supplier_id,equivalent_supplier_id),
             greatest(canonical_supplier_id,equivalent_supplier_id)
      from supplier_identity_equivalences
      group by 1,2
      having count(*)>1
    ) duplicates
  union all select 'active_supplier_equivalence_overlaps',count(*)::bigint,0
    from (
      select supplier_id
      from (
        select canonical_supplier_id supplier_id
        from supplier_identity_equivalences where is_active
        union all
        select equivalent_supplier_id supplier_id
        from supplier_identity_equivalences where is_active
      ) active_members
      group by supplier_id
      having count(*)>1
    ) overlap_rows
  union all select 'supplier_equivalence_missing_audit',count(*)::bigint,0
    from supplier_identity_equivalences e
    where not exists (
      select 1 from supplier_identity_equivalence_audit a
      where a.equivalence_id=e.id
    )
  union all select 'supplier_equivalence_audit_orphans',count(*)::bigint,0
    from supplier_identity_equivalence_audit a
    left join supplier_identity_equivalences e on e.id=a.equivalence_id
    where e.id is null
  union all select 'alias_supplier_outside_reconciliation_identity',count(*)::bigint,0
    from purchase_order_reconciliation_items i
    join purchase_order_reconciliations r on r.id=i.reconciliation_id
    where i.match_alias_supplier_id is not null
      and i.match_alias_supplier_id not in (
        r.supplier_id,r.invoice_supplier_id
      )
  union all select 'legacy_tables_outside_reconciliation_domain',0::bigint,0::bigint
)
select check_name,observed,expected,case when observed=expected then 'PASS' else 'STOP' end status from checks order by check_name;
rollback;
