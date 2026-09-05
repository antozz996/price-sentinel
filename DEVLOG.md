# 📓 DEVLOG — Price Sentinel
## Registro tecnico delle modifiche AI-assistite

> **Scopo:** Questo file traccia in modo cronologico ogni modifica significativa apportata al progetto, con dettaglio tecnico su *cosa* è stato cambiato, *perché*, e *come*.
> Aggiornato ad ogni sessione di lavoro con l'AI.

---

### [2026-09-05] Rimozione completa: Sentinel Copilot & integrazione provider AI

**File toccati:**
- `backend/app/services/ai_engine.py` (decommissionato)
- `backend/app/api/v1/ai.py` (decommissionato)
- `backend/app/api/v1/router.py`
- `frontend/src/components/SentinelCopilot.tsx` (decommissionato)
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/package.json`
- `DEVLOG.md`
**Tipo:** Refactor / Deprecation

#### Problema / Obiettivo
Richiesta esplicita dell'utente di eliminare completamente il widget Sentinel Copilot e tutta la parte di intelligenza artificiale collegata a provider esterni (Groq/LLM) da backend e frontend.

#### Soluzione implementata
- **Frontend**: rimosso il componente `SentinelCopilot` e il relativo rendering globale in `App.tsx`; rimosse tutte le regole CSS `.copilot-floating-btn` e `.copilot-chat-window` da `index.css`; dismesso `react-markdown` dalle dipendenze del frontend.
- **Backend**: rimossa la route `/api/v1/ai` dal router principale FastAPI (`backend/app/api/v1/router.py`); dismessi il modulo `ai.py` e il servizio `ai_engine.py` (interfaccia HTTP a Groq API, tools SQL e chiamate esterne).

---

### [2026-09-05] Fix: responsive UX & docked bottom bar per carrello ordini da mobile

**File toccati:**
- `frontend/src/index.css`
- `frontend/src/components/SectorOrderBuilder.tsx`
- `frontend/src/components/SentinelCopilot.tsx`
- `frontend/src/App.tsx`
- `DEVLOG.md`
**Tipo:** Bug Fix / UX

#### Problema / Obiettivo
Su dispositivi mobili e tablet, il banner fluttuante del carrello ordini (`SectorOrderBuilder`) occupava uno spazio verticale eccessivo (~40% dello schermo), nascondeva la lista dei prodotti, troncava il testo del pulsante d'azione ("Elabora Buoni d'Ordine Whats...") e veniva parzialmente coperto dall'icona circolare del widget AI Copilot. La causa era il breakpoint rigido a 768px (invece di 1024px usato dal resto dell'app per la visualizzazione mobile) e la mancanza di uno stato reattivo combinato nel componente.

#### Soluzione implementata
- **Docked Bar Compatta su Mobile/Tablet (<= 1024px)**: la barra ora si ancora elegantemente al fondo dello schermo con safe-area padding e altezza contenuta (~58px), mostrando in una sola riga pulita: icona carrello, totale colli, spesa totale in verde, pulsante "Dettagli ▾" e pulsante CTA compatto "Elabora Ordine".
- **Drawer Dettagli Espandibile**: cliccando su "Dettagli ▾" o sulle info del carrello, un drawer a scomparsa si apre verso l'alto mostrando sede di consegna, data, fornitori coinvolti, note, promozioni attive e il pulsante di sicurezza "Svuota Carrello".
- **Disaccoppiamento Copilot**: aggiunto posizionamento elevato a `bottom: 84px` per Sentinel Copilot su mobile e in modalità ordini (`copilot-order-mode`), impedendo qualunque sovrapposizione con i pulsanti d'azione.
- **Rilevamento Reattivo a Doppio Livello**: introdotto `isMobileScreen` in React combinato con `@media (max-width: 1024px)` per garantire una transizione fluida su ogni risoluzione senza glitch visivi o testo troncato.

---

### [2026-08-29] Fix: nome completo prodotto negli ordini di settore

**File toccati:**
- `backend/app/api/v1/ordini.py`
- `backend/tests/sector_orders_whatsapp_unit.py`
- `DEVLOG.md`
**Tipo:** Bugfix

#### Problema / Obiettivo
Il nome rapido assegnato internamente a un prodotto per facilitarne la ricerca (per esempio `LAVA PIATTI`) veniva riportato anche nell'ordine destinato al fornitore.

#### Soluzione implementata
- Anteprima ordine, messaggio WhatsApp e riga salvata usano sempre il nome canonico completo del prodotto letto dal database.
- Il nome rapido resta disponibile esclusivamente per ricerca e selezione nel catalogo.
- Il codice articolo del fornitore continua a essere recuperato dall'alias approvato.
- Aggiunto un test di regressione che distingue nome rapido, nome canonico, descrizione alias e valore inviato dal client.

---

## Formato entry

```
### [YYYY-MM-DD] Titolo breve
**Branch:** nome-branch
**File toccati:** lista file
**Tipo:** Bug Fix | Feature | Refactor | Hotfix | Config
**Autore:** AI (antigravity) + nome utente

#### Problema / Obiettivo
Descrizione del contesto.

#### Soluzione implementata
Dettaglio tecnico della soluzione.

#### Note / Gotcha
Eventuali avvertenze o cose da sapere.
```

---

## 📅 2026-08-18

---

### [2026-08-18] Fix: selezione prodotto nella modal "Associa a un prodotto esistente"

**Branch:** `feat/smart-price-sheet-policies`
**File toccati:** `frontend/src/components/ProductIdentityManager.tsx`
**Tipo:** Bug Fix
**Commit:** `09abc00` (tentativo 1) → `[commit push in corso]` (fix definitivo)

#### Problema
Nel modal "Associa a un prodotto esistente" del `ProductIdentityManager`, selezionare un prodotto dalla lista — anche cliccandoci sopra esplicitamente — non veniva registrato. Il sistema continuava a mostrare:
> *"Seleziona il prodotto canonico da associare."*

nonostante l'item fosse visivamente evidenziato in blu.

#### Causa radice (due problemi combinati)

**Problema 1 — `onChange` non scatta su single-item select:**
Quando la ricerca restringeva i risultati a un solo prodotto, il browser evidenziava quell'opzione in blu (comportamento nativo del `<select size>`) ma non emetteva `onChange` — perché nessun click reale era avvenuto. `selectedExistingProductId` rimaneva `''`.

**Problema 2 — `required` intercetta il submit nativo:**
Il `<select>` aveva l'attributo `required`. Il browser HTML5 esegue la validazione nativa del form **prima** che il gestore `onSubmit` di React venga chiamato. Se il valore corrente del select è `''` (stringa vuota — nessuna opzione formalmente selezionata), il browser blocca la submit silenziosamente, impedendo anche al click esplicito di funzionare correttamente in alcuni scenari.

#### Soluzione — Primo tentativo (parziale)
Auto-selezione nell'`onChange` del campo di ricerca quando i risultati si riducono a 1. Risolveva il caso "single result" ma non il click esplicito con `required`.

#### Soluzione finale — Custom Div Listbox
Sostituito completamente il `<select required size={N}>` con una **listbox custom** basata su `<div role="listbox">` con righe `<div role="option">` cliccabili via `onClick`.

Vantaggi:
- `onClick` è deterministico — nessuna ambiguità di browser su quando scatta
- Nessun attributo `required` HTML5 → nessuna validazione nativa che intercetta
- Stato `selectedExistingProductId` aggiornato immediatamente al click
- Visual feedback chiaro: border blu sull'intero listbox quando qualcosa è selezionato, riga in blu con bordo sinistro per l'item attivo, riga di conferma `✓ Selezionato: ...` sotto la lista
- Comportamento hover via `onMouseEnter`/`onMouseLeave` per responsività

L'auto-selezione su singolo risultato (nel search `onChange`) è stata mantenuta come miglioramento UX aggiuntivo.

#### Note
- Il `<select>` è stato rimosso interamente — nessun attributo `required` HTML5 rimane nella form. La validazione è gestita interamente da React in `resolveWorkItem()` tramite `!selectedExistingProductId`.
- Se in futuro si cambia la logica di filtro in `filteredExistingProducts` (computed var), va aggiornata anche la replica nell'`onChange` della ricerca testuale.

---

### [2026-08-18] Feature: Nuova sezione "Categorie & Fornitori"

**Branch:** `main`
**File toccati:**
- `backend/app/models/categories.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/categories.py`
- `backend/app/api/v1/categories.py`
- `backend/app/api/v1/router.py`
- `frontend/src/components/CategorySupplierManager.tsx`
- `frontend/src/App.tsx`
- `DEVLOG.md`
**Tipo:** Feature
**Autore:** AI (antigravity) + utente

#### Problema / Obiettivo
Necessità di un'area gestionale dedicata per definire il catalogo delle categorie merci (settori merceologici Ho.Re.Ca.) e mappare con facilità quali categorie sono trattate/abilitate per ciascun fornitore del gruppo.

#### Soluzione implementata
1. **Modello e Database:**
   - Creata tabella `master_categories` con id, nome, descrizione, colore, is_active, timestamp.
   - Utilizzo della tabella `supplier_category_capabilities` per associazioni puntuali fornitore ↔ categoria con audit trail.

2. **Backend API (`/api/v1/categories`):**
   - `GET /` — Elenco categorie master con conteggi dinamici di prodotti e fornitori associati.
   - `POST /` — Creazione categoria personalizzata con colore identificativo.
   - `POST /seed-defaults` — Popolamento rapido di 16 categorie merceologiche standard Ho.Re.Ca. (Beverage, Birre, Alcolici, Vini, Acqua, Caffetteria, Monouso, Detergenza, Packaging, Ortofrutta, Carni, Ittico, Latticini, Surgelati, Dispensa, Attrezzature).
   - `PUT /{id}` e `DELETE /{id}` — Modifica e cancellazione categorie master con aggiornamento a cascata.
   - `GET /matrix` — Matrice bidimensionale completa di tutti i fornitori non archiviati × tutte le categorie con stato abilitazione.
   - `POST /toggle` — Toggle istantaneo di abilitazione/disabilitazione categoria per fornitore.
   - `PUT /matrix` — Aggiornamento massivo abilitazioni fornitore.

3. **Frontend Component (`CategorySupplierManager.tsx`):**
   - Integrato nel menu principale sotto **🟣 Catalogo → "Categorie e fornitori"**.
   - Barra KPI con Categorie totali, Fornitori attivi e % di copertura mappatura.
   - Due sotto-viste:
     - **Mappatura Fornitori ↔ Categorie**: supporto a vista a *Schede Fornitore* con chip interattivi e toggle istantaneo, e vista a *Griglia Matrice* tabellare con scroll orizzontale e colonne fisse.
     - **Catalogo Categorie Master**: gestione schede categorie con badge colore, conteggi prodotti/fornitori, pulsanti modifica/elimina e modal per creazione personalizzata con palette colori.

4. **Integrazione di navigazione:**
   - Aggiunto route e switch-case in `App.tsx`.
   - Aggiornato bundle compilato in `frontend/dist/`.

#### Note
- L'abilitazione delle categorie guida direttamente le logiche di matching fattura e le raccomandazioni del Listino Smart.

---

### [2026-08-18] Feature: "Estrai Listino da Fatture" per Fornitori (es. LINEA CATERING)

**Branch:** `main`
**File toccati:**
- `backend/app/services/excel_import.py`
- `backend/app/api/v1/listino.py`
- `frontend/src/components/PriceListManager.tsx`
- `DEVLOG.md`
**Tipo:** Feature
**Autore:** AI (antigravity) + utente

#### Problema / Obiettivo
Quando vengono caricate molteplici fatture elettroniche di un fornitore senza avere a priori il listino prezzi pattuito (es. 20 fatture caricate di LINEA CATERING), l'utente ha bisogno di estrapolare in automatico tutti gli articoli acquistati, calcolare i prezzi e generare il Listino Master in 1 clic o scaricarlo in Excel.

#### Soluzione implementata
1. **Backend Service & API (`/api/v1/listino`):**
   - `GET /extract-from-invoices/{fornitore_id}`:
     - Aggrega tutte le righe fattura per codice/descrizione/UoM.
     - Calcola il prezzo pattuito secondo 3 strategie selezionabili:
       - ⚡ `latest` (prezzo della fattura più recente)
       - 📉 `min` (miglior prezzo storico pagato)
       - 📊 `avg` (prezzo medio ponderato sui volumi)
     - Genera SKU intelligenti con prefisso fornitore.
     - Supporto parametro `format=excel` che genera e scarica al volo un file `.xlsx` precompilato e formattato.
   - `POST /import-from-invoices/{fornitore_id}`:
     - Esegue l'importazione diretta delle voci nel database (`ListinoMaster`), aggiornando prezzi o inserendo nuovi record con data inizio validità.

2. **Frontend (`PriceListManager.tsx`):**
   - Aggiunta scheda primaria **"✨ Estrai da Fatture"** in cima a *Listini Master*.
   - Selettore fornitore con caricamento real-time.
   - Toggle criterio di prezzo (Ultimo / Minimo / Medio).
   - Tabella anteprima prodotti con conteggio fatture, prezzo unitario e UoM.
   - Due azioni rapide:
     - 📥 **Scarica Excel (.xlsx)**
     - 🚀 **Importa subito a Listino**

---

### [2026-08-18] Refactor & Feature: "Configurazione Sede" potenziata con Gestione Completa Location & Soglie

**Branch:** `main`
**File toccati:**
- `frontend/src/components/ClientOnboarding.tsx`
- `DEVLOG.md`
**Tipo:** Feature / Refactor
**Autore:** AI (antigravity) + utente

#### Problema / Obiettivo
La pagina "Configurazione sede" (ClientOnboarding) era precedentemente limitata a una semplice visualizzazione di sola lettura della checklist di avanzamento e a pochi input tecnici, senza permettere all'utente di creare, modificare o visualizzare in modo chiaro le sedi aziendali del gruppo.

#### Soluzione implementata
Riprogettato completamente il componente `ClientOnboarding.tsx` trasformandolo in un hub gestionale operativo a 2 schede:
1. **Scheda "Gestione Sedi & Location":**
   - KPI bar riassuntiva: Totale Sedi registrate, Fatture ricevute dalla sede attiva, Manager/Utenti associati.
   - Griglia di schede responsive per ciascuna sede (es. *Lido Playaluna SRL*), con Partita IVA Cessionario (11 cifre), badge tipologia locale (Balneare, Ristorante, Discoteca, Eventi).
   - Pulsante **"+ Nuova Sede"** e modale con validazione P.IVA e tipologia.
   - Pulsanti rapidi **✏️ Modifica** ed **🗑️ Elimina** per ogni sede.
   - Link rapido *"Configura Soglie & Diagnostica"*.

2. **Scheda "Soglie di Controllo & Diagnostica":**
   - Selettore sede attiva.
   - Barra di avanzamento readiness e checklist 8-step dello stato operativo della sede.
   - Form per configurare e salvare le soglie di tolleranza prezzo (€ e %), soglia anomalia grave (€), giorni limite per note di credito e solleciti, e switch notifiche.

---

*Fine delle entry per questa data.*
