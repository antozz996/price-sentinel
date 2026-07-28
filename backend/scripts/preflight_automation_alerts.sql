\set ON_ERROR_STOP on
begin transaction read only;

select
  check_name,
  observed_count,
  expected_count,
  case when observed_count = expected_count then 'PASS' else 'STOP' end status
from (
  select 'required_tables'::text, count(*)::bigint, 2::bigint
  from information_schema.tables
  where table_schema = 'public'
    and table_name in ('automation_alerts', 'automation_runs')

  union all
  select 'required_checks', count(*), 3
  from pg_catalog.pg_constraint
  where connamespace = 'public'::regnamespace
    and conname in (
      'ck_automation_alerts_severity',
      'ck_automation_alerts_status',
      'ck_automation_runs_status'
    )

  union all
  select 'alert_location_orphans', count(*), 0
  from automation_alerts alert
  left join location venue on venue.id = alert.location_id
  where alert.location_id is not null and venue.id is null

  union all
  select 'alert_acknowledger_orphans', count(*), 0
  from automation_alerts alert
  left join utenti actor on actor.id = alert.acknowledged_by
  where alert.acknowledged_by is not null and actor.id is null

  union all
  select 'alert_timestamp_inconsistency', count(*), 0
  from automation_alerts
  where last_detected_at < first_detected_at
     or (status = 'acknowledged' and (
       acknowledged_by is null or acknowledged_at is null
     ))
     or (status = 'resolved' and resolved_at is null)

  union all
  select 'duplicate_alert_dedupe_keys', count(*), 0
  from (
    select dedupe_key
    from automation_alerts
    group by dedupe_key
    having count(*) > 1
  ) duplicates

  union all
  select 'automation_run_inconsistency', count(*), 0
  from automation_runs
  where alerts_detected < 0
     or alerts_created < 0
     or alerts_resolved < 0
     or (status in ('completed', 'failed', 'skipped') and completed_at is null)
) checks(check_name, observed_count, expected_count)
order by check_name;

rollback;
