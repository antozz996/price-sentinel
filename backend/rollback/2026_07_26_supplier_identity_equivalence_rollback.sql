\set ON_ERROR_STOP on
begin;

do $$
begin
  if to_regclass('public.supplier_identity_equivalences') is null then
    raise exception 'rollback_blocked: supplier equivalence migration is not installed';
  end if;
  if exists (
    select 1
    from public.purchase_order_reconciliations
    where supplier_equivalence_id is not null
  ) then
    raise exception
      'rollback_blocked: operational reconciliations use supplier equivalences';
  end if;
  if exists (select 1 from public.supplier_identity_equivalences)
     or exists (select 1 from public.supplier_identity_equivalence_audit) then
    raise exception
      'rollback_blocked: supplier equivalence or audit data exists';
  end if;
end
$$;

drop index if exists public.ix_po_reconciliation_items_alias_supplier;
alter table public.purchase_order_reconciliation_items
  drop constraint if exists fk_po_reconciliation_items_alias_supplier,
  drop column if exists match_alias_supplier_id;

alter table public.purchase_order_reconciliations
  drop constraint if exists ck_po_reconciliations_supplier_identity_audit,
  drop constraint if exists fk_po_reconciliations_equivalence_approver,
  drop constraint if exists fk_po_reconciliations_supplier_equivalence,
  drop constraint if exists fk_po_reconciliations_invoice_supplier;
drop index if exists public.ix_po_reconciliations_supplier_equivalence;
drop index if exists public.ix_po_reconciliations_invoice_supplier;
alter table public.purchase_order_reconciliations
  drop column if exists supplier_equivalence_reason_snapshot,
  drop column if exists supplier_equivalence_used_at,
  drop column if exists supplier_equivalence_approved_at,
  drop column if exists supplier_equivalence_approved_by,
  drop column if exists supplier_equivalence_id,
  drop column if exists invoice_supplier_id;

drop trigger if exists supplier_identity_equivalence_audit
  on public.supplier_identity_equivalences;
drop function if exists public.audit_supplier_identity_equivalence();
drop trigger if exists supplier_identity_equivalence_guard
  on public.supplier_identity_equivalences;
drop function if exists public.enforce_supplier_identity_equivalence();
drop table public.supplier_identity_equivalence_audit;
drop table public.supplier_identity_equivalences;

commit;
