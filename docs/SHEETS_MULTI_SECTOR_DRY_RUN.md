# Google Sheets Multi-sector Sync — P1 Dry Run

## Stato / safety

**Solo lettura.** Questo modulo NON ha endpoint di scrittura, non usa il database Price Sentinel, non registra prezzi pattuiti, non lancia job periodici, non modifica Google Sheets e non manda ordini. I valori di Google Sheets/Gemini sono osservazioni e proposte, **non prezzi pattuiti finche' approvati**.

Dipendenza: PR P0 `fix/smart-price-sheet-sync-p0` (revisione del flusso anteprima/commit). Il ramo P1 va valutato separatamente: nessun deploy e nessun merge senza gate.

## Documento di riferimento

Workbook ufficiale: **santo graal** (ID da conservare solo in configurazione protetta; non hardcoded nel repository pubblico).

Le 18 schede mappate:

| Tab | Tipo | Utilizzo P1 |
| --- | --- | --- |
| FOOD | Sorgente | Prodotto A, UoM B, MARR C, MELIUS D, DAC E, ORIZZONTI F, DI PALO H, FONTANELLA CARNI I; G note Orizzonti, J calcolo ignorato |
| BEVERAGE | Sorgente | Prodotto A, UoM B, NAVAS C, ORIZZONTI D, 3F E, PASCARELLA F, CASA D'AMBRA G; H:J calcoli ignorati |
| COMPARAZIONE MATERIALI | Sorgente | Prodotto B, UoM C, VEMO D, KITO E, EUROCARTA F, ALPHA G, PROMOCART H, MUNDO I; J note, L pezzature, K calcolo ignorato |
| FRUTTA E VERDURA | Sorgente | Prodotto A, UoM B; MG FRUTTA C (+ note D), DEMETRA E (+ UoM F, note G), BONTA DELL'ORTO H (+ UoM I, note J) |
| GIOCATTOLI | Sorgente in **sola revisione** | Descrizione C, UoM D; valori L ANTONIO, M GIOVANNI; verifica identita' fornitore, sconti F:H e IVA K prima di qualunque uso |
| CONTROLLO_ESCLUSIONI | Controllo | A riga, B prodotto, C fornitore, F stato; le esclusioni di FOOD bloccano i singoli prezzi conservandoli |
| ORIZZONTI BEVERAGE | Supporto | BEVERAGE colonna D contiene gia' una lookup; non leggere due volte gli stessi prezzi |
| KITO VEMO  | Supporto | Riga-per-riga con fornitore e quantita' ordinata, NON fonte di prezzi pattuiti automatica; attenzione allo spazio finale del nome |
| BEVERAGE DA INVIARE | Preparazione | Non-import |
| MATERIALI DA INVIARE | Preparazione | Non-import |
| PRICE SENTINEL di FRUTTA E VERDURA 1 | Vista derivata | Non-import per evitare doppioni |
| DASHBOARD FORNITORI | Report | Non-import |
| ORDINI DAC | Modello ordini | Non-import |
| ORDINI MELIUS | Modello ordini | Non-import |
| ORDINI MARR | Modello ordini | Non-import |
| ORDINE - MG FRUTTA | Modello ordini | Non-import |
| ORDINE - BONTA DELL'ORTO | Modello ordini | Non-import |
| ORDINE - DEMETRA | Modello ordini | Non-import |

Il lettore controlla le intestazioni dei fornitori **prima** di leggere il settore. Prezzi a zero/non numerici sono bloccati o ignorati, le unità inconciliabili rimangono bloccate, le esclusioni sono applicate per coppia **prodotto/fornitore**; se il registro esclusioni manca, FOOD non viene elaborato. I numeri di riga sono solo riferimenti diagnostici, non ID canonici.

## Come provarlo in locale (senza credenziali)

```bash
cd backend
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -p 'test_sheet_sync_dry_run.py' -v
PYTHONPATH=. python scripts/sheet_sync_preview.py --fixture tests/fixtures/sheets_sync_synthetic.json
```

Il fixture usa solo dati inventati. I dati reali non vengono aggiunti al repository.

## Come leggere il documento Google reale (quando disponibile la credenziale)

1. Creare una **service account Google Cloud** dedicata. Abilitare Google Sheets API.
2. Condividere il singolo spreadsheet con l'indirizzo email della service account come **Visualizzatore**. Non rendere il documento pubblico e non concedere scrittura.
3. Conservare il file credenziali JSON in un secret manager o percorso backend protetto, **fuori** dal repository. Non incollare JSON/chiavi nella chat o nel foglio.
4. Impostare `SHEETS_SOURCE_ID` e `SHEETS_SERVICE_ACCOUNT_FILE` in un ambiente di test isolato; per eseguire una sola anteprima locale:

```bash
cd backend
PYTHONPATH=. python scripts/sheet_sync_preview.py \
  --spreadsheet-id "$SHEETS_SOURCE_ID" \
  --service-account-file "$SHEETS_SERVICE_ACCOUNT_FILE" \
  --output /tmp/price-sentinel-sheets-preview.json
```

Il token OAuth ha esclusivamente lo scope `spreadsheets.readonly`, e il client utilizza solo richieste HTTP GET. Legge i valori non formattati (per non scambiare un testo con un prezzo numerico) e, salvo `--skip-notes`, le note di cella. Confronta il titolo esatto `santo graal`, rifiutando un file diverso. Il fuso del documento attuale e' **America/Los_Angeles**; la futura decorrenza dei contratti si gestira' esplicitamente in **Europe/Rome**, non interpretando le date senza verifica.

**Protezione del report:** il JSON contiene prezzi e note dei fornitori; salvarlo in una destinazione privata esterna al repository, con permessi ristretti; non caricarlo nei log di GitHub Actions.

## Significato degli stati

- `blocked`: esclusione, valore non affidabile, zero, unità per fornitore non comparabile.
- `needs_approval`: quota positiva leggibile ma manca il mapping canonico e l'approvazione delle condizioni pattuite.
- `auto_eligible`: **non emesso da P1**; sara' possibile solo con registro mapping e policy contrattuali preautorizzate da Price Sentinel.

I prezzi possono avere piu' di quattro decimali nelle formule Sheets; vengono preservati e marcati per revisione, mai arrotondati silenziosamente.

## Prossimi gate

- Convalidare collaudo su dati reali in read-only (5 settori, note, esclusioni).
- Creare registry canonico `product_id/supplier_id` con mapping esplicito. Non usare fuzzy matching o il solo numero di riga.
- Distinguere il prezzo net-to-pay dalla quotazione, il prezzo pattuito e le risultanze delle fatture.
- Definire workflow di approvazione accordo per fornitore/periodo; **gli accordi restano validi fino al nuovo listino approvato salvo scadenza esplicita**.
- Eseguire P0 E2E su DB usa-e-getta; solo dopo valutare il merge P0/P1 e il lavoro P2 staging DB.

## Verifiche e limiti

Il test con dati sintetici non e' una prova che l'accesso Google con service account funzioni sul file privato: quella prova richiede configurazione autorizzata dall'utente. Nessun sistema di sincronizzazione in background e' ancora stato attivato.
