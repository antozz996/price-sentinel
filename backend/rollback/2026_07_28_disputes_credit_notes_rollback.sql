\set ON_ERROR_STOP on
begin;

do $$
declare
  operational_rows bigint;
begin
  select
    coalesce((select count(*) from dispute_cases),0)
    + coalesce((select count(*) from dispute_credit_notes),0)
    + coalesce((select count(*) from dispute_communications),0)
  into operational_rows;

  if operational_rows > 0 then
    raise exception
      'rollback_blocked: % dispute workflow rows exist',
      operational_rows;
  end if;
end
$$;

drop table if exists dispute_audit_events;
drop table if exists dispute_credit_note_allocations;
drop table if exists dispute_credit_notes;
drop table if exists dispute_supplier_responses;
drop table if exists dispute_attachments;
drop table if exists dispute_communications;
drop table if exists dispute_case_anomalies;
drop table if exists dispute_cases;

delete from alembic_version where version_num='ls_s6_disputes';
insert into alembic_version(version_num)
select 'ls_s5_supplier_equivalence'
where not exists (select 1 from alembic_version);

commit;
