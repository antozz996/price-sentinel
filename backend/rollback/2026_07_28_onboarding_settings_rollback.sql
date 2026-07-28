\set ON_ERROR_STOP on
begin;

drop table if exists location_reconciliation_settings;

delete from alembic_version where version_num = 'ls_s8_onboarding';
insert into alembic_version(version_num)
select 'ls_s7_automation'
where not exists (select 1 from alembic_version);

commit;
