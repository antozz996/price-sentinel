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

### [2026-08-18] Fix: auto-selezione prodotto nella modal "Associa a un prodotto esistente"

**Branch:** `feat/smart-price-sheet-policies`
**File toccati:** `frontend/src/components/ProductIdentityManager.tsx`
**Tipo:** Bug Fix
**Commit:** `09abc00`

#### Problema
Nel modal "Associa a un prodotto esistente" del `ProductIdentityManager`, quando l'utente digitava nella barra di ricerca e i risultati si restringevano a **un solo prodotto**, il browser evidenziava visivamente quell'elemento nel `<select>` (sfondo blu) — ma il click non era mai avvenuto, quindi `onChange` del `<select>` non scattava mai.

Risultato: `selectedExistingProductId` rimaneva stringa vuota `''`, e al submit il sistema mostrava:
> *"Seleziona il prodotto canonico da associare."*

nonostante l'item fosse visivamente selezionato.

#### Causa radice
Il comportamento è nativo del browser HTML: un `<select>` con un'unica `<option>` la mostra selezionata **visivamente** ma **non emette `onChange`** finché l'utente non interagisce esplicitamente (click o tastiera). La logica di validazione al submit controllava `!selectedExistingProductId`, che era ancora `''`.

Secondo problema minore: le `<option>` usavano `value={product.id}` (numero), mentre lo state è una stringa — incongruenza di tipo che poteva causare mismatch sottili.

#### Soluzione implementata
1. **Auto-selezione nell'`onChange` del campo di ricerca testuale:**
   - Replica della stessa logica di filtro usata nella computed `filteredExistingProducts`
   - Se `filtered.length === 1` → chiama `setSelectedExistingProductId(String(filtered[0].id))` e azzera l'errore
   - Se l'utente modifica la ricerca e il prodotto precedentemente auto-selezionato esce dai risultati → reset a `''`

2. **`onChange` del `<select>`:**
   - Aggiunto `setResolutionError(null)` per cancellare immediatamente il messaggio di errore quando l'utente seleziona manualmente
   - Wrappato in `String(e.target.value)` per coerenza di tipo

3. **`value` delle `<option>`:**
   - Cambiato da `value={product.id}` (number) a `value={String(product.id)}` per allineamento con lo state stringa

#### Note
- La logica di filtro replicata nell'`onChange` della ricerca è intenzionalmente identica a `filteredExistingProducts` (stessa slice a 50 elementi). Se in futuro si cambia la logica di filtro principale, va aggiornata anche qui.
- Non è stata modificata la logica backend — il bug era interamente frontend.

---

*Fine delle entry per questa data.*
