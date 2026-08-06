# Price Sentinel — deploy, rollback e incident response

## Prima del deploy

1. Verificare working tree e commit atteso.
2. Eseguire build frontend, compile backend, test E2E e preflight.
3. Verificare `npm audit`, scansione segreti e `git diff --check`.
4. Creare un backup PostgreSQL custom completo, `--no-owner --no-privileges`.
5. Validare il backup con `pg_restore --list` e registrare SHA-256.
6. Annotare versione Alembic e hash delle fatture/dati economici critici.

## Ordine di rilascio

1. Mettere il servizio in maintenance se la finestra lo richiede.
2. Applicare le migrazioni in ordine:
   `ls_s6_disputes`, `ls_s7_automation`, `ls_s8_onboarding`,
   `smart_price_policy`.
3. Eseguire i preflight post-migration.
4. Caricare il nuovo backend e riavviarlo una sola volta.
5. Pubblicare il frontend compilato.
6. Validare health check, login, isolamento sedi e flussi principali.
7. Abilitare il monitor periodico solo dopo lo smoke test.

Variabili nuove, senza valori nel repository:

- `AUTOMATION_ENABLED`
- `AUTOMATION_INTERVAL_SECONDS`

Prima di `smart_price_policy` eseguire in modalità sola lettura
`backend/scripts/smart_price_sheet_preflight.sql` e verificare che la revisione corrente
sia `ls_s8_onboarding`. Non applicare la migrazione di produzione come effetto del
deploy applicativo: richiede autorizzazione e finestra esplicite.

## Rollback

Prima di eseguire un rollback verificare l'esistenza di dati operativi. Gli script:

- `backend/rollback/2026_07_28_onboarding_settings_rollback.sql`
- `backend/rollback/2026_07_28_automation_alerts_rollback.sql`
- `backend/rollback/2026_07_28_disputes_credit_notes_rollback.sql`
- `backend/rollback/smart_price_sheet_policy_guard.sql`

sono intenzionalmente protettivi e possono fermarsi. Non forzare la rimozione di
contestazioni, comunicazioni, note di credito o alert attivi. Se sono presenti dati
reali, correggere in avanti oppure ripristinare l'intero backup in un ambiente isolato
e concordare la strategia.

## Smoke test

- login valido e login errato limitato;
- dashboard e fatture leggibili;
- mapping e riconciliazioni isolati per sede;
- creazione pratica, versione comunicazione, conferma manuale;
- risposta, riconoscimento e nota di credito parziale;
- alert monitor e presa visione;
- onboarding e salvataggio soglie;
- matrice canonica, preview senza variazione listino e commit idempotente;
- assessment bloccato, raccomandazione policy e storico prezzi;
- nessuna modifica alle fatture sorgente o a `current_stock`.

## Incidenti

### Segreto esposto

Bloccare il deploy, revocare/ruotare il segreto nel gestore operativo, riavviare i
consumer e verificare i log senza stampare il nuovo valore. Ripulire la cronologia Git
solo dopo la rotazione: riscrivere Git non rende sicuro un segreto ancora valido.

### Evento bridge fallito

Non modificare manualmente i payload. Verificare inbox/outbox, firma, clock skew e
mapping; usare retry idempotente. Conservare dead letter e audit.

### Dati cross-venue

Mettere in pausa le operazioni interessate, eseguire query read-only e preservare
evidenze. Non cancellare record. Correggere policy o mapping e validare con test di
isolamento prima del riavvio.

### Migrazione fallita

Non rilanciare casualmente. Verificare se la transazione ha fatto rollback, leggere
l'errore completo, controllare lock e versione Alembic. Riprendere solo con uno stato
deterministico.
