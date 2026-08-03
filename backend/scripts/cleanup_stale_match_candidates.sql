\set ON_ERROR_STOP on

begin;

-- Rimuove esclusivamente suggerimenti ancora "pending" la cui riga fattura
-- è già stata risolta. I candidati di righe in parking e quelli da listino
-- senza invoice_line_id non vengono toccati.
with deleted as (
    delete from match_candidates candidate
    using righe_fattura invoice_line
    where candidate.invoice_line_id = invoice_line.id
      and candidate.status = 'pending'
      and invoice_line.stato_matching <> 'in_parking'
    returning candidate.id
)
select 'STALE_CANDIDATES_DELETED|' || count(*) from deleted;

select 'ACTIONABLE_CANDIDATES_REMAINING|' || count(*)
from match_candidates candidate
left join righe_fattura invoice_line on invoice_line.id = candidate.invoice_line_id
where candidate.status = 'pending'
  and (
      candidate.invoice_line_id is null
      or invoice_line.stato_matching = 'in_parking'
  );

commit;
