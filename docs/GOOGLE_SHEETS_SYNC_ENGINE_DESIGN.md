# Price Sentinel — Google Sheets Sync Engine (design esecutivo v1)

**Stato:** specifica tecnica; nessun connettore attivo, nessun deploy o aggiornamento DB.
**Decisione di business (2026-10-09):** Price Sentinel e' il sistema autorevole per i prezzi pattuiti e il controllo fatture. LiquidStock e' dismesso. Gli accordi hanno cadenza normalmente mensile, ma **rimangono validi fino al nuovo listino approvato, a meno che sia indicata una scadenza esplicita**. Nessuna scadenza automatica a 30 giorni.

## Confini e fonti di verita'

- Google Sheets FOOD + Gemini: raccolta e bonifica dei listini ricevuti; e' un'area di lavoro e non un contratto in se'.
- Price Sentinel: catalogo canonico, identita' del fornitore, accordi accettati, storico prezzi e controllo delle fatture.
- In una successiva fase, un portale fornitori inviera' proposte usando **la medesima API di staging e approvazione**. Nessun fornitore modifica direttamente un accordo in vigore.
- Le quotazioni spot o di mercato restano distinte dai prezzi **pattuiti**. I prezzi estratti dalle fatture non riscrivono automaticamente i pattuiti.

## Contratto economico e validita'

Per ciascuna coppia `product_id + supplier_id` (e ove necessario `location_id`, variante/confezione):

1. Salvare prezzo pattuito netto, prezzo di origine, unita' di prezzo, formato confezione, prezzo normalizzato, regola IVA, fonte e impronta del dato.
2. Registrare `effective_from`, `explicit_expires_on` opzionale, `approved_by`, `approved_at`, evidenza documentale, import batch, eventuale riferimento accordo.
3. Un nuovo prezzo accettato con decorrenza `D` chiude logicamente l'intervallo precedente il giorno `D-1` e inaugura il successivo, senza cancellare la vecchia versione.
4. Se **non** c'e' un rinnovo, il prezzo resta valido, salvo `explicit_expires_on`. Nessuna scadenza implicita dopo 30 giorni.
5. Se un listino futuro e' approvato in anticipo, le fatture antecedenti alla sua decorrenza usano ancora la versione precedente. Il catalogo operativo deve filtrare su `effective_from <= reference_date` oltre che sulla scadenza.
6. Una fattura si confronta con l'accordo valido alla **data di competenza economica del documento**, definita con una policy (tipicamente data del documento/fornitura, non data di upload). Mostrare esplicitamente versione e motivo della selezione.
7. Correzioni retroattive, prezzi con periodi sovrapposti e cambi di unità richiedono un workflow ad hoc e approvazione; non vanno applicati da semplici aggiornamenti automatici.

## Sorgente FOOD attuale

- `FOOD!A`: nome prodotto; `B`: UdM.
- `C:F`: MARR, MELIUS, DAC, ORIZZONTI.
- `G`: note; `H:I`: DI PALO, FONTANELLA CARNI.
- `J`: fornitore consigliato da formula, **solo informativo**, mai importato come assegnazione canonica.
- `CONTROLLO_ESCLUSIONI!A:F`: righe, prodotti, fornitori, prezzi, motivazione, stato; sei quotazioni ORIZZONTI inizialmente non comparabili.
- 240 referenze dichiarate: 201 con due o piu' fornitori numerici, 34 con uno, 5 senza; questi sono conteggi del foglio, non una verifica automatica di equivalenza commerciale.

Il connettore legge **valori non formattati**, metadati e note (per prezzi/confezioni originarie). Valori di formula non numerici, stringhe "NO", vuoti e prezzi di mercato non sono pattuiti aggiornabili. Le righe del foglio possono essere spostate: i **numeri di riga non sono ID persistenti**. Creare una mapping registry in Price Sentinel `(spreadsheet_id, sheet_id, source_product_key, product_id, supplier_key, supplier_id)`, inizialmente approvata dall'operatore. Non riassegnare prodotti con matching fuzzy automatico.

## Connettore

- Credenziali Google in backend, con accesso minimo e in sola lettura al singolo documento; nessuna chiave nel browser o nel foglio.
- Polling per snapshot ogni ~5 minuti e pulsante `Sincronizza ora`. I trigger onEdit non sono sufficienti a intercettare tutte le scritture via Gemini/API.
- Non eseguire l'import a ogni carattere modificato: usare debounce, hash deterministico e versione dello snapshot.
- `sync_batches`: sheet ID, checked_at, source revision/hash, stato, contatori; `sync_candidates`: row key stabile, supplier/product ID, prezzo letto, valuta, IVA, UdM, prezzo originario/normalizzato, note, status, reason, actor, approved evidence.
- Dedupe per sorgente + coppia ID + hash del contenuto + decorrenza. Concorrenza protetta da lock/versioni ottimistiche; il retry di un commit deve restituire il risultato originario.
- Accessi server-to-server con identita' tecnica limitata, audit e rate limit. Vietati token utente memorizzati nel foglio.

## Macchina a stati proposta

`detected -> normalized -> validated -> (auto_eligible | needs_approval | blocked) -> (committed | rejected)`.

**Auto-eligible** solo se tutte queste condizioni risultano vere:
- prodotto/fornitore associati in modo esplicito e gia' approvato, stessa entita' commerciale;
- unita' e confezione verificate, conversione deterministica, valuta e IVA definite;
- fonte di accordo gia' autorizzata dalla policy dell'acquirente per il fornitore e il periodo: un semplice valore proposto da Gemini **non equivale** a un nuovo accordo commerciale;
- nessuna esclusione attiva, variazione oltre soglia, conflitto storico o prezzo contrattuale piu' recente;
- decorrenza corretta e assenza di scadenza esplicita incompatibile;
- appartenenza al tenant/sede e privilegi di approvazione verificati.

Altrimenti il dato rimane *needs_approval* o *blocked*. Le soglie economiche sono configurabili per fornitore/categoria/periodo; **nessuna soglia unica hardcoded**. Un prezzo escluso nel foglio puo' tornare a *comparabile* solo dopo conferma in Price Sentinel. Nuove referenze, nuovi fornitori, alias ambigui e cambio di marca/composizione non si auto-creano.

**Importante:** una quotazione ben formata non diventa prezzo pattuito se manca la prova di accordo o la policy di pre-autorizzazione. Per il primo rilascio: riconciliazione iniziale e attivazione per fornitore con conferma esplicita dell'acquirente; solo gli aggiornamenti successivi coperti da regole autorizzate possono essere automatici.

## API proposte (da implementare, non ancora esistenti)

- `POST /api/v1/sheet-sync/connections` — lega lo Spreadsheet (admin).
- `POST /api/v1/sheet-sync/pull?dry_run=true` — importa uno snapshot in staging senza cambiare i listini.
- `GET /api/v1/sheet-sync/batches/{id}` — anteprima create/update/unchanged/conflict con evidenze.
- `POST /api/v1/sheet-sync/candidates/{id}/approve` — approvazione con motivazione e decorrenza.
- `POST /api/v1/sheet-sync/batches/{id}/commit` — commit idempotente **solo** delle voci auto-eligible o approvate, transazione e audit.
- `GET /api/v1/sheet-sync/history` — variazioni e rollback tramite nuova versione, mai tramite overwrite distruttivo.

Riutilizzare il parser e la logica del Listino Smart, ma non affidare al client la decisione `create_missing_products`; il profilo integrazione impone `false`. Nessuna tabella economica in produzione viene modificata finche' il percorso P0 (preview, ownership, idempotenza, lock, history, test) non e' verificato.

## Storico e KPI

- Versioni contrattuali immutabili nel contenuto economico; chiusura della validita' tracciata con audit. Conservare anche originale, normalizzato, metodo di conversione, riferimento documento.
- Andamento mese/mese e anno/anno per prodotto-fornitore, % aumento/riduzione, minimo/massimo, medie ponderate per *giorni di validita'* e per *quantita' effettivamente acquistate* (distinte).
- Raffronto prezzo pattuito vs prezzo netto fatturato **sulla versione applicabile per data**, quantitativi, differenza unitario/totale, contestazioni e note di credito.

## Piano di rilascio

1. **P0 (branch isolato):** allineare contratto API/servizio/model anteprima, proprietà della preview, idempotenza, lock, test regressione unit ed E2E su DB temporaneo.
2. **P1:** connettore read-only e snapshot; report mapping, esclusioni e normalizzazioni FOOD; nessun commit.
3. **P2:** modello staging + policy e workflow approvazioni; audit per tenant/sede.
4. **P3:** beta di sync intelligente su fornitore pilota, test fatture storiche e simulazione degli ordini, confronto di prezzi con il foglio.
5. **P4:** estensione e UI portale fornitori sulla stessa pipeline, documenti e accettazioni digitali.

**GATE:** nessun merge/deploy finche' DB migrations, preview/commit E2E, controlli tenant, retroattivita', scadenza esplicita, prova di accordo, rollback e backup non risultino verificati.
