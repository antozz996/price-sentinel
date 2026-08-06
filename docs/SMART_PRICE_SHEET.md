# Price Sentinel — Smart Price Sheet & Supplier Policy Engine

## Scopo

Il Listino Smart unifica confronto prezzi, aggiornamento massivo, qualità del
fornitore e regole di acquisto. Il catalogo `products` resta la sorgente canonica:
questo modulo non crea automaticamente prodotti o fornitori; una descrizione fattura
associata manualmente viene invece ricordata come alias approvato del fornitore.

## Modello dati

- `product_supplier_assessments`: valutazione di una coppia prodotto/fornitore,
  globale o specifica per sede. Stato `approved`, `discouraged` o `blocked`, qualità
  1–5, affidabilità consegne 0–100, validità temporale/stato attivo e motivazione
  obbligatoria per gli ultimi due stati.
- `product_supplier_assessment_audits`: snapshot prima/dopo, azione, attore e data.
- `product_purchase_policies`: modalità di selezione, fornitore preferito, qualità
  minima, premium percentuale/assoluto e abilitazione spot.
- `product_purchase_policy_audits`: audit append-only delle policy.
- `purchase_policy_deviations`: scelta operativa difforme dalla raccomandazione,
  deduplicata tramite `dedupe_key`, con stato `open`, `acknowledged`,
  `accepted_exception` o `resolved` e presa visione tracciata.
- `smart_price_sheet_previews`: token, hash, payload validato, scadenza e risultato
  idempotente del commit.
- `products.order_name`: nome rapido facoltativo e univoco per la ricerca durante la
  creazione ordine; `canonical_name` e SKU restano l'identità primaria.
- `supplier_category_capabilities`: eccezioni esplicite per rendere un settore
  disponibile o indisponibile a un fornitore, senza cancellare lo storico.

### Nome principale, descrizione fattura e nome rapido

Il **nome canonico**, mostrato nell'interfaccia come **prodotto principale**, è la
scheda interna unica e leggibile. Per esempio `Guanti nitrile nero 100 pezzi` è un
solo prodotto principale anche se VEMO scrive `GUANTI NITR NERI TG.L 100PZ` e un
altro fornitore usa una descrizione diversa. Queste diciture sono alias legati al
fornitore; lo SKU è soltanto l'identificatore tecnico interno.

Il **nome rapido ordine** (per esempio `GUANTI`) è una scorciatoia facoltativa scelta
dall'utente. La priorità di riconoscimento è: nome principale/SKU esatto, alias
fattura già approvato, nome rapido esatto, infine ricerca fuzzy nel flusso ordini.
Quindi un nome reale non viene mai sostituito da un nome rapido omonimo.

Una configurazione con `location_id` prevale sulla corrispondente configurazione
globale (`location_id IS NULL`). Indici univoci parziali impediscono duplicati nello
stesso scope.

## Matrice

`GET /api/v1/smart-price-sheet/matrix` pagina i prodotti canonici e carica in batch
fornitori, prezzi attivi, prezzi spot, assessment e policy. Ogni riga espone:

- `absolute_cheapest_supplier_id`: minimo numerico osservato;
- `recommended_supplier_id`: migliore offerta che rispetta la policy;
- `selected_supplier_id`: scelta automatica effettiva, assente in modalità manuale;
- offerte con eleggibilità, motivi di esclusione, qualità e tipo contratto/spot.
- `eligible_supplier_ids`: fornitori pertinenti, inferiti da alias approvati,
  listini, fatture e assessment reali, estesi alle categorie già trattate.

Le celle fuori settore non sono modificabili e vengono respinte anche dalla preview.
Le pagine hanno massimo 500 righe lato API; il Foglio prezzi carica l'intero catalogo
attivo, mentre la matrice di confronto resta paginata a 50 righe.

La scheda **Settori fornitori** rende questa logica modificabile senza interventi
tecnici. Per ogni categoria sono disponibili tre modalità:

- `Automatico`: deduce il settore da fatture, listini, alias e valutazioni esistenti;
- `Abilitato`: mostra sempre il fornitore per quel settore;
- `Escluso`: lo nasconde sempre, anche se esistono dati commerciali storici.

## Incolla, mapping e preview

Il parser accetta TSV da Excel/Google Sheets e CSV con `;`, `,` o `|`. Nel formato
nuovo la prima colonna è `Nome rapido ordine (facoltativo)`, la seconda mostra e
identifica il prodotto reale leggibile e le successive identificano i fornitori. Lo
SKU resta un identificatore tecnico interno e non viene mostrato nel foglio. Il formato storico con
prodotto nella prima colonna resta compatibile. Sono supportati decimali italiani e
internazionali, con massimo quattro cifre decimali.

La risoluzione automatica avviene solo per corrispondenza esatta e univoca. Il client
può inviare:

```json
{
  "text": "Nome rapido ordine\tProdotto reale\tFornitore A\nACQUA\tAcqua 75cl\t1,20",
  "supplier_mapping": {"Fornitore A": 12},
  "product_mapping": {"Acqua 75cl": 44},
  "effective_date": "2026-08-06",
  "default_uom": "piece"
}
```

La preview:

- non inserisce né aggiorna `listino_master`;
- riporta create/update/unchanged/error con vecchio e nuovo valore;
- blocca prodotti/fornitori ambigui, prezzi invalidi,
  coppie duplicate, prezzi attivi multipli e fornitori fuori settore;
- mostra separatamente le modifiche ai nomi rapidi;
- genera un token associato all'utente, valido 30 minuti.

`POST /cell-preview` usa lo stesso motore per la modifica di una singola cella.

## Commit e storico prezzi

`POST /commit` richiede `confirm: true`. Il backend blocca la preview con
`SELECT ... FOR UPDATE`, verifica attore/scadenza/stato e rilegge la versione prezzo.
Se il listino è cambiato dopo la preview risponde `409` e non salva nulla.

Per un aggiornamento la versione precedente riceve la data di fine e viene inserita
una nuova riga attiva in `listino_master`, mantenendo l'alias approvato corrispondente.
Se l'utente ha risolto manualmente una descrizione mai vista, il commit crea anche
l'alias fornitore-prodotto: dalle importazioni successive il riconoscimento è automatico.
Il token passa a `committed` con il risultato: un retry restituisce lo stesso risultato
senza una seconda versione.

## Assessment, policy e ranking

Il motore usa esclusivamente `Decimal`:

1. ordina tutte le offerte e identifica il minimo assoluto;
2. esclude bloccati, sconsigliati, qualità sotto soglia e spot non consentiti;
3. calcola il tetto premium rispetto al minimo idoneo;
4. entro il tetto preferisce il fornitore esplicito, poi la qualità, poi il prezzo;
5. in modalità manuale usa il fornitore preferito obbligatorio;
6. in modalità minimo assoluto seleziona il minimo e mantiene gli avvisi qualitativi.

Con premium zero il risultato è il miglior prezzo idoneo. Un fornitore bloccato resta
visibile come possibile minimo assoluto, ma non viene raccomandato.

`resolve_order_item` usa questo risultato e mantiene `best_offer` per compatibilità,
aggiungendo minimo, raccomandato, selezionato, policy e motivazione. Le deviazioni
policy sono eventi commerciali separati dalle anomalie contrattuali delle fatture.
La ricerca ordine prova prima SKU e nome canonico/reale esatti, poi il nome rapido e
infine il fuzzy matching: un nome reale vince sempre su un nome rapido omonimo.

## Permessi

- Lettura matrice, storico, assessment, policy e deviazioni: utente autenticato;
  un manager è limitato alla propria sede.
- Modifica prezzi, assessment e policy: solo admin.
- Registrazione deviazione: utente autenticato, sempre nello scope consentito.
- Preview e commit appartengono all'admin che li ha creati.

## Endpoint

```text
GET  /api/v1/smart-price-sheet/matrix
GET  /api/v1/smart-price-sheet/supplier-sectors
PUT  /api/v1/smart-price-sheet/supplier-sectors
POST /api/v1/smart-price-sheet/preview
POST /api/v1/smart-price-sheet/cell-preview
POST /api/v1/smart-price-sheet/commit
GET  /api/v1/smart-price-sheet/history
GET  /api/v1/smart-price-sheet/audit
GET  /api/v1/smart-price-sheet/assessments
PUT  /api/v1/smart-price-sheet/assessments
GET  /api/v1/smart-price-sheet/policies
PUT  /api/v1/smart-price-sheet/policies
GET  /api/v1/smart-price-sheet/deviations
POST /api/v1/smart-price-sheet/deviations
PATCH /api/v1/smart-price-sheet/deviations/{id}
```

## Test

- `backend/tests/smart_price_sheet_unit.py`: 24 controlli parser, ranking e precedenza settori.
- `backend/tests/smart_price_sheet_e2e.py`: 26 controlli API su PostgreSQL usa-e-getta.
- `backend/tests/smart_price_sheet_test_base.sql`: solo base isolata per l'E2E, mai
  eseguita in produzione.
- `npm run build` e `npm run lint` per il frontend.
- `alembic upgrade head --sql` e downgrade offline per coerenza della migrazione.

## Deploy e rollback

1. Eseguire `backend/scripts/smart_price_sheet_preflight.sql` in sola lettura.
2. Verificare backup, hash e revisione `ls_s8_onboarding`.
3. Con autorizzazione esplicita, applicare `alembic upgrade smart_supplier_sectors`.
4. Pubblicare backend e frontend, poi eseguire lo smoke test del runbook.

Per il rollback eseguire prima
`backend/rollback/smart_price_sheet_policy_guard.sql`: se rileva dati nelle nuove
tabelle interrompe l'operazione. Senza dati, il downgrade target è
`ls_s8_onboarding`. Con dati reali si preferisce una correzione in avanti o un piano
di esportazione approvato; non forzare il drop delle tabelle.
