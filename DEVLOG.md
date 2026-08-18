# 📓 DEVLOG — Price Sentinel
## Registro tecnico delle modifiche AI-assistite

> **Scopo:** Questo file traccia in modo cronologico ogni modifica significativa apportata al progetto, con dettaglio tecnico su *cosa* è stato cambiato, *perché*, e *come*.
> Aggiornato ad ogni sessione di lavoro con l'AI.

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

*Fine delle entry per questa data.*
