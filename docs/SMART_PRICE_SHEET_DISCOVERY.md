# Smart Price Sheet & Supplier Policy Engine — Discovery

Data ricognizione: 2026-08-06
Branch di lavoro: `feat/smart-price-sheet-policies`

## Vincoli operativi

- Il database contiene dati reali: non sono consentiti reset, truncate, drop, reseed o cleanup distruttivi.
- Le modifiche allo schema saranno solo additive tramite una nuova revisione Alembic; la migrazione non deve essere applicata alla produzione senza autorizzazione esplicita.
- Il catalogo `products` e gli alias approvati `supplier_product_aliases` restano l'unica identità prodotto autorevole.
- `listino_master` resta la sorgente dei prezzi contrattuali e della loro cronologia. Il nuovo flusso non crea fornitori o prodotti implicitamente.
- Le modifiche locali preesistenti a `docker-compose.yml` e i file non tracciati presenti sono fuori perimetro e devono essere preservati.

## Stato attuale riutilizzabile

### Backend

- `Product` espone SKU, nome canonico, classificazione, formato e unità di confronto.
- `SupplierProductAlias` collega prodotto e fornitore, contiene codice/descrizione/formato e uno stato di approvazione.
- `ListinoMaster` contiene prezzi per fornitore/SKU e date di validità; il servizio `save_append_only_price` gestisce creazione, invariato e nuova versione.
- `/intelligence/cross-supplier` produce una matrice di contratti e minimi spot, ma lavora per SKU e sceglie solo il minimo numerico.
- `resolve_order_item` risolve prodotto, alias, prezzi normalizzati, quantità e alternative; oggi `best_offer` coincide sempre con l'offerta più economica.
- Le tabelle di equivalenza fornitori, contestazioni e automazione forniscono pattern già adottati per audit, deduplicazione e JSONB.
- L'autorizzazione distingue admin e manager; il manager ha `location_id`, l'admin può operare globalmente.

### Frontend

- `CrossSupplierMatrix` è la base funzionale della matrice, con ricerca e filtro colonne fornitori.
- `PriceListManager` copre il listino tradizionale e lo storico.
- `OrderOptimizer` consuma il contratto storico dell'ottimizzatore ordini.
- `App.tsx` usa stato locale, non React Router; “Comparazione fornitori” è già una voce admin.
- Lo stack è React/TypeScript/Vite senza framework di griglia: una tabella virtualmente semplice e paginata è preferibile a una dipendenza spreadsheet pesante.

## Lacune da colmare

1. Nessuna valutazione prodotto-fornitore (`approved`, `discouraged`, `blocked`) né qualità 1–5.
2. Nessuna policy di acquisto globale o per sede.
3. Nessuna distinzione fra minimo assoluto, raccomandato dalla policy e scelta effettiva.
4. Nessuna importazione da clipboard con mapping esplicito, preview obbligatoria e commit idempotente.
5. Nessuna evidenza persistente degli scostamenti dalla policy.
6. La matrice esistente non parte dal catalogo canonico e quindi non mostra in modo affidabile celle mancanti.
7. L'aggiornamento listino esistente chiude la versione corrente modificandone la scadenza: il nuovo flusso deve centralizzare questa operazione, mantenere l'alias e impedire doppie versioni su retry.

## Disegno scelto

### Persistenza additiva

- `product_supplier_assessments`: stato, qualità, motivazione e scope globale/sede.
- `product_supplier_assessment_audits`: snapshot prima/dopo e attore per ogni modifica.
- `product_purchase_policies`: modalità (`manual`, `best_eligible_price`, `absolute_lowest`), fornitore preferito, soglie qualità/premium e spot.
- `product_purchase_policy_audits`: audit delle policy.
- `purchase_policy_deviations`: evento deduplicato quando una scelta effettiva differisce dalla raccomandazione.
- `smart_price_sheet_previews`: token server-side con hash, scadenza, payload validato e risultato di commit; il prezzo non viene scritto prima della conferma.

Le righe globali usano `location_id IS NULL`; le righe di sede prevalgono sulle globali. Indici univoci parziali impediscono doppioni per lo stesso scope.

### Flusso clipboard/cella

1. L'utente incolla TSV/CSV oppure modifica una cella.
2. Il parser riconosce delimitatore, intestazioni e prezzi italiani/internazionali.
3. Prodotti e fornitori sono risolti esclusivamente contro entità esistenti; le ambiguità restano bloccanti.
4. La preview mostra create/update/unchanged/error, vecchio e nuovo prezzo, unità e mapping.
5. Il server salva un token breve con hash e scadenza.
6. Il commit usa quel token una sola volta, ri-valida le entità e applica le versioni prezzi in una transazione.
7. Un retry restituisce lo stesso risultato senza creare nuove righe.

### Motore di raccomandazione

Il ranking usa `Decimal` e produce sempre tre concetti separati:

- `absolute_cheapest`: minimo numerico, anche se commercialmente bloccato;
- `recommended_offer`: migliore offerta eleggibile secondo assessment e policy;
- `selected_offer`: scelta automatica o manuale effettiva.

Un fornitore bloccato non è eleggibile, uno sconsigliato è escluso salvo policy esplicita, e qualità/premium possono far preferire un prezzo leggermente superiore. In assenza di policy il comportamento resta compatibile: migliore offerta eleggibile, con fallback al minimo se non esistono assessment.

## API previste

- `GET /smart-price-sheet/matrix`
- `POST /smart-price-sheet/preview`
- `POST /smart-price-sheet/commit`
- `POST /smart-price-sheet/cell-preview`
- `GET /smart-price-sheet/history`
- CRUD/upsert per `/smart-price-sheet/assessments` e `/smart-price-sheet/policies`
- `GET /smart-price-sheet/deviations`

Le letture rispettano lo scope dell'utente; le scritture di prezzi/policy restano admin. I payload monetari sono serializzati come stringhe decimali.

## Piano migrazione e rollback

- Nuova revisione con `down_revision = ls_s8_onboarding`.
- Solo nuove tabelle, FK, check e indici; nessuna modifica o backfill sulle tabelle esistenti.
- Script preflight solo lettura: head Alembic, collisioni nomi, FK orfane, duplicati logici e conteggi baseline.
- Downgrade in ordine inverso; script operativo di rollback rifiuta la rimozione se le nuove tabelle contengono dati, salvo decisione umana esplicita.
- La migrazione sarà validata offline e su database di test, non sulla produzione.

## Piano test

- Unit test parser: tab/comma/semicolon, virgola decimale, celle vuote, duplicati, header e prezzi invalidi.
- Unit test ranking: blocked/discouraged, qualità minima, premium, preferito, manuale, fallback e precisione Decimal.
- Test API/transazionali: preview senza write su `listino_master`, commit, retry idempotente, token scaduto, mapping ambiguo, RBAC/scope e audit.
- Test regressione: contratto/spot e forma storica di `best_offer` nell'order resolver.
- Frontend: TypeScript build ed ESLint; verifica manuale dei quattro tab Matrice, Incolla, Qualità e regole, Storico.

## Rischi e mitigazioni

- **SKU nullable o non univoco:** la matrice usa `product_id` come chiave; lo SKU resta solo visuale. Import bloccato per prodotti senza identificazione univoca.
- **Alias multipli dello stesso fornitore:** selezione deterministica dell'alias approvato; ambiguità segnalata in preview.
- **Concorrenza al commit:** token bloccato `FOR UPDATE`, vincoli univoci e transazione unica.
- **Date append-only:** la nuova versione parte dalla data scelta e la precedente termina il giorno precedente quando possibile, evitando sovrapposizioni.
- **N+1:** query aggregate/batch per prodotti, fornitori, listini, assessment e policy.
- **Compatibilità:** campi esistenti dell'ottimizzatore non vengono rimossi; i campi policy sono aggiuntivi.
