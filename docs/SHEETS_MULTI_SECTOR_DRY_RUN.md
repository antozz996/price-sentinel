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
3. **Non creare chiavi private JSON.** Il client ora usa Application Default Credentials (ADC). Per GitHub Actions, usare un provider OIDC Workload Identity Federation e `google-github-actions/auth@v3`, che genera durante il job un file *di configurazione federata*, non una chiave privata.
4. Configurare `SHEETS_SOURCE_ID` e `SHEETS_EXPECTED_SOURCE_ID` sul runner autorizzato, entrambi con l'ID dello stesso workbook. L'azione Google imposta `GOOGLE_APPLICATION_CREDENTIALS` a un file di configurazione ADC effimero.
5. Eseguire una singola anteprima (infrastruttura di test, senza log dei prezzi):

```bash
cd backend
PYTHONPATH=. python scripts/sheet_sync_preview.py \
  --spreadsheet-id "$SHEETS_SOURCE_ID" \
  --output /tmp/price-sentinel-sheets-preview.json
```

Il token OAuth ha esclusivamente lo scope `spreadsheets.readonly`, e il client utilizza solo richieste HTTP GET. Legge i valori non formattati (per non scambiare un testo con un prezzo numerico) e, salvo `--skip-notes`, le note di cella. Confronta il titolo esatto `santo graal`, rifiutando un file diverso. Il fuso del documento attuale e' **America/Los_Angeles**; la futura decorrenza dei contratti si gestira' esplicitamente in **Europe/Rome**, non interpretando le date senza verifica.

**Protezione del report:** il JSON contiene prezzi e note dei fornitori; salvarlo in una destinazione privata esterna al repository, con permessi ristretti; non caricarlo nei log di GitHub Actions.

## Abilitazione GitHub Actions tramite Workload Identity Federation (separata dal codice)

**NON ancora configurato**: l'API Google Sheets è abilitata nel progetto `price-sentinel-integrations` e `santo graal` è condiviso come Viewer con `ps-sheets-reader@price-sentinel-integrations.iam.gserviceaccount.com`. Non è stato creato un provider WIF, né concesso a GitHub il diritto di impersonare tale account.

Operazioni riservate alla fase di configurazione controllata in Google Cloud:

1. Creare un pool WIF dedicato, es. `price-sentinel-ci`, e un provider OIDC con issuer `https://token.actions.githubusercontent.com`. Non assegnare ruoli generali di progetto al service account.
2. Mappare almeno `google.subject=assertion.sub` e `attribute.repository=assertion.repository`, in aggiunta a eventuali attributi necessari per le condizioni. Applicare una condizione che ammetta esclusivamente `antozz996/price-sentinel`, la *branch* `refs/heads/feat/google-sheets-multisheet-dry-run`, l'evento `workflow_dispatch` e, se disponibile, `assertion.repository_id` per prevenire repository-name reuse. **Verificare il claim OIDC nel provider prima di salvare**.
3. Concedere `roles/iam.workloadIdentityUser` **sulla sola service account** a un principalSet del pool limitato all'attributo repository. L'ulteriore restrizione a branch/evento deve essere applicata dal provider. Non aggiungere ruoli Owner/Editor/Viewer al progetto.
4. Sul job GitHub autorizzato utilizzare `permissions: {contents: read, id-token: write}` e `google-github-actions/auth@v3` con `workload_identity_provider` completo e `service_account`; l'azione deve precedere Python. Usare un workflow **manuale** con verifica dell'esatta branch e nessun evento `pull_request` per l'accesso live, perché il repository è pubblico.
5. Prima eseguire un test minimo di metadata del workbook con token temporaneo; poi un dry-run dei 5 settori e del registro esclusioni. Non pubblicare JSON prezzi nei log o negli artifact non protetti.
6. Se Google richiede altre API per impersonare la service account, abilitare solo quelle strettamente necessarie e dopo verifica. **Non creare chiavi private statiche**.

Per la VPS Hetzner non presumere che esista una sorgente OIDC federabile. Il WIF del runner GitHub è un **collaudo separato**, non abilita automaticamente il backend di produzione sulla VPS. La soluzione server permanente richiede progettazione dedicata.

La nuova `GoogleSheetsReadOnly` usa `google.auth.default(scopes=[READONLY_SCOPE])`. Sotto WIF l'ADC legge la configurazione temporanea creata dall'azione GitHub, che non contiene una private key permanente. Il test `test_sheet_sync_google_auth.py` verifica il percorso di caricamento senza credenziali reali.

## Collaudo live manuale WIF (preparato, non ancora eseguito)

Configurazione Google Cloud **già verificata**:

- Project: `price-sentinel-integrations` / project number `876130258139`.
- Provider: `projects/876130258139/locations/global/workloadIdentityPools/price-sentinel-github-actions/providers/github-oidc`, issuer ufficiale GitHub, stato ACTIVE.
- Condizione provider: repository `antozz996/price-sentinel`, repository ID `1230041589`, branch `refs/heads/feat/google-sheets-multisheet-dry-run`, evento `workflow_dispatch`.
- La service account `ps-sheets-reader@price-sentinel-integrations.iam.gserviceaccount.com` ha un binding `roles/iam.workloadIdentityUser` **a livello di service account**, legato al principalSet del repository ID. Lo Sheet è condiviso come Viewer.

Il file `.github/workflows/sheet-sync-dry-run.yml` include ora un job `live-google-readonly` che si attiva **solo manualmente** sul branch di collaudo. Il job originale per le fixture sintetiche continua a funzionare su push/PR ma **non riceve token OIDC né credenziali reali**.

Per il primo collaudo:

1. In GitHub → Settings → Secrets and variables → Actions, salvare un **repository secret** chiamato `PS_SHEETS_SOURCE_ID` con l'ID dello Spreadsheet privato originale. Non inserirlo nel workflow, nei commit, nelle issue o nei log. Il job verifica il digest SHA-256 dell'ID atteso prima di autenticarsi, senza stampare il valore.
2. GitHub richiede normalmente che un workflow `workflow_dispatch` esista sul branch `main` per comparire nella UI. **Non modificare `main` senza approvazione.** Il workflow sul branch di sviluppo è già stato registrato tramite esecuzioni `push` e `pull_request`; è possibile tentare un dispatch manuale via GitHub CLI con un account autenticato e write access:

   ```bash
   gh workflow run sheet-sync-dry-run.yml -R antozz996/price-sentinel \
     --ref feat/google-sheets-multisheet-dry-run -f operation=metadata
   ```

   Se GitHub restituisce `404` o `workflow does not have workflow_dispatch trigger`, fermarsi e richiedere autorizzazione a creare **solo** lo stub del workflow sul branch default; nessun merge di PR P0/P1 o deploy.
3. Il primo test legge **esclusivamente i metadati** del documento (titolo e presenza delle 5 schede sorgente + esclusioni). Non legge prezzi.
4. Soltanto dopo esito positivo e consenso al test completo, avviare con `-f operation=dry_run`. Questo legge i valori dei 5 settori e note, produce **solo conteggi aggregati nei log** e zero write/price commit/artifact.
5. Per il test si usano **solo credenziali temporanee WIF** tramite `google-github-actions/auth@v3`. `gha-creds-*.json` è escluso tramite `.gitignore`.

Il successo dei test offline su GitHub non significa che l'autenticazione WIF o l'accesso Google Sheets siano già stati testati con dati reali.

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
