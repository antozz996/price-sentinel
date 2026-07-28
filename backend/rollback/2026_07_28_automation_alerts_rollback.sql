\set ON_ERROR_STOP on
begin;

do $$
begin
  if exists (
    select 1 from automation_alerts
    where status in ('open', 'acknowledged')
  ) then
    raise exception 'rollback_blocked: active automation alerts exist';
  end if;
end
$$;

drop table if exists automation_runs;
drop table if exists automation_alerts;

delete from alembic_version where version_num = 'ls_s7_automation';
insert into alembic_version(version_num)
select 'ls_s6_disputes'
where not exists (select 1 from alembic_version);

commit;
