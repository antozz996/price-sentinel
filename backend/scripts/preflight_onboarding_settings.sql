\set ON_ERROR_STOP on
begin transaction read only;

select
  check_name,
  observed_count,
  expected_count,
  case when observed_count = expected_count then 'PASS' else 'STOP' end status
from (
  select
    'required_table'::text,
    count(*)::bigint,
    1::bigint
  from information_schema.tables
  where table_schema = 'public'
    and table_name = 'location_reconciliation_settings'

  union all
  select 'required_checks', count(*), 2
  from pg_catalog.pg_constraint
  where connamespace = 'public'::regnamespace
    and conname in (
      'ck_location_reconciliation_settings_amounts',
      'ck_location_reconciliation_settings_days'
    )

  union all
  select 'settings_location_orphans', count(*), 0
  from location_reconciliation_settings settings
  left join location venue on venue.id = settings.location_id
  where venue.id is null

  union all
  select 'settings_user_orphans', count(*), 0
  from location_reconciliation_settings settings
  left join utenti creator on creator.id = settings.created_by
  left join utenti updater on updater.id = settings.updated_by
  where creator.id is null or updater.id is null

  union all
  select 'settings_invalid_values', count(*), 0
  from location_reconciliation_settings
  where price_tolerance_absolute < 0
     or price_tolerance_percent < 0
     or important_anomaly_threshold <= 0
     or stalled_reconciliation_days not between 1 and 90
     or missing_credit_note_days not between 1 and 180
) checks(check_name, observed_count, expected_count)
order by check_name;

rollback;
