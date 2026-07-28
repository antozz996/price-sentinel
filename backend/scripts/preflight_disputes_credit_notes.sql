\set ON_ERROR_STOP on

begin transaction read only;

select
  check_name,
  observed_count,
  expected_count,
  case when observed_count = expected_count then 'PASS' else 'STOP' end as status
from (
  select
    'required_tables'::text as check_name,
    count(*)::bigint as observed_count,
    8::bigint as expected_count
  from information_schema.tables
  where table_schema = 'public'
    and table_name = any(array[
      'dispute_cases',
      'dispute_case_anomalies',
      'dispute_communications',
      'dispute_attachments',
      'dispute_supplier_responses',
      'dispute_credit_notes',
      'dispute_credit_note_allocations',
      'dispute_audit_events'
    ])

  union all
  select 'required_constraints', count(*), 15
  from pg_catalog.pg_constraint
  where connamespace = 'public'::regnamespace
    and conname = any(array[
      'ck_dispute_cases_status',
      'ck_dispute_cases_amounts_nonnegative',
      'ck_dispute_cases_amount_consistency',
      'ck_dispute_cases_terminal_reason',
      'ck_dispute_case_anomalies_one_source',
      'ck_dispute_case_anomalies_amounts',
      'ck_dispute_communications_channel',
      'ck_dispute_communications_status',
      'ck_dispute_communications_hash',
      'ck_dispute_attachments_size',
      'ck_dispute_attachments_sha256',
      'ck_dispute_supplier_responses_channel',
      'ck_dispute_credit_notes_source',
      'ck_dispute_credit_notes_status',
      'ck_dispute_credit_notes_amount'
    ])

  union all
  select 'required_unique_constraints', count(*), 6
  from pg_catalog.pg_constraint
  where connamespace = 'public'::regnamespace
    and contype = 'u'
    and conname = any(array[
      'uq_dispute_cases_code',
      'uq_dispute_case_anomalies_reconciliation',
      'uq_dispute_case_anomalies_legacy',
      'uq_dispute_credit_notes_invoice',
      'uq_dispute_credit_notes_document',
      'uq_dispute_credit_note_allocations_item'
    ])

  union all
  select 'case_location_or_supplier_orphans', count(*), 0
  from dispute_cases dc
  left join location l on l.id = dc.location_id
  left join fornitori f on f.id = dc.supplier_id
  where l.id is null or f.id is null

  union all
  select 'case_amount_inconsistency', count(*), 0
  from dispute_cases
  where requested_amount < 0
     or recognized_amount < 0
     or recovered_amount < 0
     or unrecovered_amount < 0
     or recognized_amount > requested_amount
     or recovered_amount > recognized_amount
     or unrecovered_amount <> requested_amount - recovered_amount

  union all
  select 'terminal_case_without_reason', count(*), 0
  from dispute_cases
  where status in ('closed', 'cancelled')
    and length(btrim(coalesce(manual_close_reason, ''))) < 8

  union all
  select 'case_reconciliation_context_mismatch', count(*), 0
  from dispute_cases dc
  join purchase_order_reconciliations por on por.id = dc.reconciliation_id
  left join liquidstock_venue_mappings lvm
    on lvm.liquidstock_venue_id = por.venue_id
  where lvm.location_id is distinct from dc.location_id
     or por.supplier_id is distinct from dc.supplier_id
     or por.venue_id is distinct from dc.liquidstock_venue_id

  union all
  select 'case_anomaly_orphans', count(*), 0
  from dispute_case_anomalies dca
  left join dispute_cases dc on dc.id = dca.dispute_case_id
  where dc.id is null

  union all
  select 'case_anomaly_source_invalid', count(*), 0
  from dispute_case_anomalies
  where (reconciliation_anomaly_id is not null)::integer
      + (legacy_anomaly_id is not null)::integer <> 1

  union all
  select 'case_anomaly_amount_inconsistency', count(*), 0
  from dispute_case_anomalies
  where claimed_amount <= 0
     or recognized_amount < 0
     or recovered_amount < 0
     or recognized_amount > claimed_amount
     or recovered_amount > recognized_amount

  union all
  select 'case_aggregate_amount_drift', count(*), 0
  from dispute_cases dc
  join (
    select
      dispute_case_id,
      sum(claimed_amount) as requested_amount,
      sum(recognized_amount) as recognized_amount,
      sum(recovered_amount) as recovered_amount
    from dispute_case_anomalies
    group by dispute_case_id
  ) totals on totals.dispute_case_id = dc.id
  where dc.requested_amount <> totals.requested_amount
     or dc.recognized_amount <> totals.recognized_amount
     or dc.recovered_amount <> totals.recovered_amount

  union all
  select 'communication_hash_invalid', count(*), 0
  from dispute_communications
  where message_hash !~ '^[0-9a-f]{64}$'

  union all
  select 'communication_case_orphans', count(*), 0
  from dispute_communications communication
  left join dispute_cases dc on dc.id = communication.dispute_case_id
  where dc.id is null

  union all
  select 'attachment_metadata_invalid', count(*), 0
  from dispute_attachments
  where size_bytes <= 0
     or size_bytes > 10485760
     or size_bytes <> octet_length(content)
     or sha256 !~ '^[0-9a-f]{64}$'

  union all
  select 'supplier_response_cross_case', count(*), 0
  from dispute_supplier_responses response
  left join dispute_communications communication
    on communication.id = response.communication_id
  left join dispute_attachments attachment
    on attachment.id = response.attachment_id
  where (response.communication_id is not null
          and communication.dispute_case_id is distinct from response.dispute_case_id)
     or (response.attachment_id is not null
          and attachment.dispute_case_id is distinct from response.dispute_case_id)

  union all
  select 'credit_note_context_mismatch', count(*), 0
  from dispute_credit_notes note
  join dispute_cases dc on dc.id = note.dispute_case_id
  left join fatture invoice on invoice.id = note.fattura_id
  where note.location_id <> dc.location_id
     or note.supplier_id <> dc.supplier_id
     or (note.fattura_id is not null and (
       invoice.id is null
       or invoice.location_id <> note.location_id
       or invoice.fornitore_id <> note.supplier_id
       or invoice.tipo_documento::text <> 'TD04'
     ))

  union all
  select 'credit_note_allocation_cross_case', count(*), 0
  from dispute_credit_note_allocations allocation
  join dispute_credit_notes note on note.id = allocation.credit_note_id
  join dispute_case_anomalies anomaly on anomaly.id = allocation.case_anomaly_id
  where note.dispute_case_id <> anomaly.dispute_case_id

  union all
  select 'credit_note_overallocated', count(*), 0
  from dispute_credit_notes note
  join (
    select credit_note_id, sum(amount) as allocated_amount
    from dispute_credit_note_allocations
    group by credit_note_id
  ) allocation on allocation.credit_note_id = note.id
  where allocation.allocated_amount > note.total_amount

  union all
  select 'case_without_creation_audit', count(*), 0
  from dispute_cases dc
  where not exists (
    select 1
    from dispute_audit_events event
    where event.dispute_case_id = dc.id
      and event.action = 'case_created'
  )
) checks
order by check_name;

rollback;
