# Price Sentinel V2 — Invarianti provvisorie del Listino Master

**Ambito:** branch di sviluppo V2. Nessuna modifica retroattiva, deploy o migrazione automatica. Questa politica è in fase di review prima del merge.

## 1. Autorità dei dati
- **Prezzo fatturato**: osservazione da XML/FatturaPA, utile a controlli ed analisi. Non prova un accordo commerciale.
- **Prezzo pattuito**: prezzo contrattuale approvato. Può derivare solo da un percorso di conferma esplicita e verificabile.
- L'import comparativo V2 approvato con token firmato è il solo percorso automatico di scrittura listino attualmente lasciato disponibile dalle guardrail P0.
- Le cinque API legacy di creazione/importazione/update/delete senza approvazione sono temporaneamente bloccate (HTTP 409); import Excel standard ancora consultabile con `dry_run=true`.
- Nessun record storico di Listino Master può essere cancellato fisicamente dalla vecchia API.

## 2. Decorrenze degli accordi (date civili Europe/Rome)
Il modello attuale memorizza date `DATE` senza ora. Per impedire sovrapposizioni:

| Operazione | Inizio nuovo prezzo | Fine prezzo precedente |
| --- | --- | --- |
| Nuovo prodotto senza accordi applicabili | Oggi | N/A |
| Cambio prezzo o UoM di contratto attivo | Domani | Oggi incluso |
| Nuovo accordo approvato | 30 giorni di calendario, decorrenza inclusa | Scade alla fine del 30° giorno |
| Seconda modifica prima dell'inizio di un prezzo futuro | Bloccata 409 | Nessuna modifica |
| Conflitto con intervallo già presente nello storico | Bloccato 409 | Nessuna modifica |

La selezione del contratto per una fattura richiede **esattamente una** versione temporalmente applicabile. In caso di date malformate o più contratti sovrapposti, il matching rifiuta di scegliere un prezzo arbitrario (ritorna `None`), rimandando il documento alla revisione.

**Limitazione del modello:** l'import da file comparativo non implementa una data di decorrenza scelta da utente o un'approvazione con ora. Pertanto un cambio accettato oggi è applicabile alle fatture datate **domani**, non alle fatture datate oggi. La regola va mantenuta esplicita in anteprima.

## 3. Validità mensile
La regola commerciale per Price Sentinel è una validità garantita di **30 giorni di calendario, inclusa la data di decorrenza**. Alla scadenza il prezzo non è più applicabile automaticamente alle nuove fatture: il documento resta senza prezzo contrattuale e passa a revisione fino a una nuova approvazione. Un rinnovo è una nuova revisione append-only, non un'estensione silenziosa dello storico.

## 4. Sicurezza / limiti
- Qualsiasi approvazione che tenti un inserimento ambiguo fallisce prima del commit. Transazione atomica e advisory lock restano attivi.
- Fornitori con P.IVA tecnica da import restano disabilitati per ordinazione commerciale.
- V1 e produzione non vengono modificati da queste PR.
- I test E2E usano un PostgreSQL creato nel runner GitHub e lo eliminano con il runner; non usano segreti di produzione.
- Lo storico *già corrotto* non viene riparato automaticamente. In caso di sovrapposizione è richiesta una bonifica supervisionata, con audit legale.
- La governance va estesa anche a eventuali ulteriori endpoint di scrittura, contratti specifici per tenant, limiti UOM e approvazione su date di validità.

## 5. Gate prima del rilascio
1. PR #4 (parser comparativo) e PR #7 (guardrail scritture) approvate nell'ordine.
2. CI PostgreSQL E2E e Staging Isolation verdi sul commit finale di questa modifica.
3. Riesame della policy di decorrenza da parte dell'owner commerciale.
4. QA manuale in staging isolato con dati sintetici e simulazioni di fatture retroattive.
5. Nessun merge o deploy alla produzione senza approvazione specifica.

Vedi [Issue #5](https://github.com/antozz996/price-sentinel/issues/5) e [Issue #6](https://github.com/antozz996/price-sentinel/issues/6).
