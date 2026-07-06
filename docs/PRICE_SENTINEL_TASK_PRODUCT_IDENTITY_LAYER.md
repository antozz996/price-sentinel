# Price Sentinel — Task Operativa: Product Identity Layer & Order Resolver

## Obiettivo
Implementare il metodo che permette all'utente di scrivere un nome interno/canonico, ad esempio `BICCHIERE CAFFE`, e ottenere automaticamente il fornitore più conveniente tra tutti i nomi alternativi usati dai fornitori.

Il sistema non deve confrontare semplicemente stringhe. Deve:

1. riconoscere il prodotto interno deciso dall'utente;
2. collegare i nomi dei fornitori a quel prodotto tramite alias approvati;
3. normalizzare confezioni, litri, kg, pezzi e bottiglie;
4. confrontare il prezzo unitario normalizzato;
5. proporre il fornitore più economico;
6. mandare in Parking Area i casi ambigui.

---

## Regola madre

```text
Non confronto nomi.
Confronto prodotti canonici.

Non confronto prezzi confezione.
Confronto prezzi normalizzati.

Non scelgo il più simile.
Scelgo il più economico tra prodotti approvati come identici o equivalenti.
```

---

## Esempio funzionale

Input utente:

```text
BICCHIERE CAFFE - 10 confezioni
```

Prodotto canonico interno:

```text
sku_interno: BICCHIERE_CAFFE
canonical_name: Bicchiere caffè
category: monouso
comparison_unit: piece
volume_ml: 80
```

Alias fornitori:

```text
Eurocarta -> BICCH. CAFFE 80CC X100
Navas -> BICCHIERE CAFFE BIANCO 75ML PZ100
Altro -> BICCHIERINO CAFFE MONOUSO PZ50
```

Output atteso:

```text
Prodotto richiesto: BICCHIERE CAFFE
Migliore fornitore: Eurocarta
Nome fornitore: BICCH. CAFFE 80CC X100
Prezzo confezione: 2,50 €
Pezzi per confezione: 100
Prezzo normalizzato: 0,025 €/pz
Totale stimato per 10 confezioni: 25,00 €

Alternative:
1. Navas — 0,028 €/pz
2. Altro — 0,031 €/pz
```

---

## Fase 1 — Modelli DB da verificare/aggiungere

### 1. Product
Catalogo interno unico, deciso dall'utente.

Campi minimi:

```python
id: int
sku_interno: str  # unique, index
canonical_name: str
normalized_name: str
brand: str | None
category: str | None
subcategory: str | None
volume_ml: int | None
weight_g: int | None
unit_count: int | None
container_type: str | None
comparison_unit: str  # piece, liter, kg, bottle, box
is_commodity: bool
is_active: bool
created_at: datetime
updated_at: datetime
```

Note:
- `sku_interno` è stabile e non deve cambiare facilmente.
- `canonical_name` è il nome leggibile scelto dall'utente.
- `normalized_name` serve per ricerche e matching.
- `comparison_unit` governa la normalizzazione prezzo.

---

### 2. SupplierProductAlias
Collega il nome/codice fornitore al prodotto canonico.

```python
id: int
supplier_id: int  # FK fornitori.id
product_id: int  # FK products.id
supplier_code: str | None
raw_description: str
normalized_description: str
ean: str | None
pack_qty: int | None
volume_ml: int | None
weight_g: int | None
container_type: str | None
confidence_score: int
status: str  # approved, pending, rejected
source: str  # invoice, excel_import, manual, ai_suggestion
created_at: datetime
updated_at: datetime
```

Indici/constraint consigliati:

```text
unique(supplier_id, supplier_code) where supplier_code is not null
index(supplier_id, normalized_description)
index(ean)
index(product_id)
```

Regola:
- Se alias `approved`, può essere usato automaticamente per ordini e fatture.
- Se alias `pending`, va mostrato in Parking Area.
- Se alias `rejected`, non deve essere riproposto come match automatico.

---

### 3. ProductEquivalenceGroup
Serve per prodotti non identici ma commercialmente alternativi.

Esempio:

```text
ACQUA_50CL_PET_GROUP
- Acqua Electa 50cl pet
- Acqua Ferrarelle 50cl pet
- Acqua Lete 50cl pet
```

Modelli:

```python
ProductEquivalenceGroup:
    id: int
    name: str
    normalized_name: str
    category: str | None
    comparison_unit: str
    is_active: bool

ProductEquivalenceGroupItem:
    id: int
    group_id: int
    product_id: int
    priority: int | None
    is_preferred: bool
```

Regola fondamentale:
- `Product` = stesso prodotto.
- `ProductEquivalenceGroup` = alternativa accettabile ma non identica.

---

### 4. MatchCandidate
Buffer per casi ambigui.

```python
id: int
source_type: str  # invoice_line, price_list_row, order_text
source_id: int | None
supplier_id: int | None
raw_description: str
normalized_description: str
candidate_product_id: int
score: int
reason: str
block_flag: bool
status: str  # pending, approved, rejected
created_at: datetime
resolved_at: datetime | None
resolved_by_user_id: int | None
```

---

## Fase 2 — Normalizzazione testo

Aggiornare `backend/app/services/normalization.py`.

Funzioni richieste:

```python
def normalize_text(text: str) -> str:
    """Normalizza descrizioni prodotto eliminando rumore e abbreviazioni."""


def extract_volume_ml(text: str) -> int | None:
    """Estrae 75cl, 0.75 lt, 750 ml, 80cc e converte in ml."""


def extract_weight_g(text: str) -> int | None:
    """Estrae kg, gr, g e converte in grammi."""


def extract_pack_qty(text: str) -> int | None:
    """Estrae x100, pz 100, conf. 100, ct 24, box 6."""


def extract_container_type(text: str) -> str | None:
    """Riconosce pet, vetro, lattina, carta, plastica, bio, box, bag."""


def infer_category(text: str) -> str | None:
    """Inferisce categorie base: acqua, soft_drink, monouso, vino, spirits, food."""
```

Abbreviazioni da gestire subito:

```text
bicch -> bicchiere
bicch. -> bicchiere
pz -> pezzi
p.z. -> pezzi
conf -> confezione
ct -> cartone
crt -> cartone
bt -> bottiglia
bott -> bottiglia
lt -> litro
cl -> centilitro
ml -> millilitro
cc -> millilitro
gr -> grammi
kg -> chilogrammi
```

---

## Fase 3 — Matching Engine

Aggiornare `backend/app/services/matching.py`.

### Funzione principale

```python
def resolve_invoice_line_product(
    db,
    fornitore_id: int,
    raw_description: str,
    supplier_code: str | None = None,
    ean: str | None = None,
) -> dict:
    ...
```

Output:

```python
{
    "decision": "auto_match" | "needs_review" | "parking",
    "product_id": int | None,
    "sku_interno": str | None,
    "score": int,
    "reason": str,
    "block_flag": bool,
    "candidates": list[dict],
}
```

### Priorità matching

#### Livello 1 — EAN
Se EAN presente e già associato a un alias approvato:

```text
score = 100
decision = auto_match
```

#### Livello 2 — codice fornitore
Se `supplier_code` è già presente tra gli alias approvati dello stesso fornitore:

```text
score = 100
decision = auto_match
```

#### Livello 3 — descrizione alias approvata
Se `normalized_description` corrisponde a un alias approvato dello stesso fornitore:

```text
score = 98
decision = auto_match
```

#### Livello 4 — attributi + fuzzy
Calcolare score su:

```text
similarità nome: max 45 punti
categoria uguale: +15
brand uguale: +10
volume uguale: +15
peso uguale: +15
pack coerente: +10
container coerente: +5
```

Blocchi severi:

```text
brand diverso su prodotto branded -> block_flag = true
volume diverso oltre tolleranza -> block_flag = true
peso diverso oltre tolleranza -> block_flag = true
categoria diversa -> block_flag = true
```

Decisione:

```text
score >= 90 e block_flag false -> auto_match
score >= 70 -> needs_review
score < 70 -> parking
```

Nota: `auto_match` creato da fuzzy deve generare alias `pending` o `approved`?
Decisione: per sicurezza, il primo auto_match fuzzy crea alias `pending_auto`, visibile in Validation/Parking, ma utilizzabile solo se confidence >= 95 e senza blocchi. In produzione, gli ordini devono usare solo alias `approved`.

---

## Fase 4 — Normalizzazione prezzo

Funzione richiesta:

```python
def normalize_price_for_comparison(
    price: Decimal,
    quantity: Decimal,
    invoice_uom: str | None,
    product: Product,
    alias: SupplierProductAlias | None = None,
) -> NormalizedPriceResult:
    ...
```

Output:

```python
NormalizedPriceResult(
    normalized_unit_price=Decimal,
    comparison_unit="piece" | "liter" | "kg" | "bottle" | "box",
    pack_qty=int | None,
    explanation=str,
)
```

### Regole

#### comparison_unit = piece
Esempio bicchieri, tovaglioli, cannucce.

```text
prezzo_normalizzato = prezzo_confezione / pack_qty
```

Se manca `pack_qty`, usare:
1. alias.pack_qty;
2. product.unit_count;
3. estrazione da descrizione;
4. se ancora mancante -> `needs_review`, perché il prezzo non è confrontabile.

#### comparison_unit = liter
Esempio liquidi.

```text
prezzo_per_litro = prezzo_confezione / (pack_qty * volume_ml / 1000)
```

#### comparison_unit = kg
Esempio food/pesce/carne/caffè.

```text
prezzo_per_kg = prezzo_confezione / (pack_qty * weight_g / 1000)
```

#### comparison_unit = bottle
Esempio vino/spumante/alcolici dove si vuole confrontare a bottiglia.

```text
prezzo_per_bottiglia = prezzo_confezione / pack_qty
```

---

## Fase 5 — Resolver ordine

Creare/aggiornare `backend/app/services/order_resolver.py`.

### Funzione principale

```python
def resolve_order_item(
    db,
    query: str,
    requested_qty: Decimal = Decimal("1"),
    allow_equivalent: bool = False,
    location_id: int | None = None,
) -> dict:
    ...
```

Output:

```python
{
    "query": "BICCHIERE CAFFE",
    "matched_product": {
        "product_id": 1,
        "sku_interno": "BICCHIERE_CAFFE",
        "canonical_name": "Bicchiere caffè"
    },
    "decision": "resolved" | "needs_review" | "not_found",
    "best_offer": {
        "supplier_id": 2,
        "supplier_name": "Eurocarta",
        "supplier_product_name": "BICCH. CAFFE 80CC X100",
        "supplier_code": "BC80X100",
        "pack_qty": 100,
        "price": "2.5000",
        "normalized_unit_price": "0.0250",
        "comparison_unit": "piece",
        "estimated_total": "25.0000"
    },
    "alternatives": [...],
    "warnings": []
}
```

### Logica

1. Normalizza la query utente.
2. Cerca prodotto interno:
   - match esatto su `sku_interno`;
   - match esatto su `normalized_name`;
   - fuzzy su `canonical_name`.
3. Recupera alias approvati per quel product_id.
4. Recupera prezzi attivi del fornitore.
5. Normalizza ogni prezzo.
6. Ordina per `normalized_unit_price` crescente.
7. Restituisce migliore offerta + alternative.
8. Se `allow_equivalent = true`, include anche prodotti nello stesso `ProductEquivalenceGroup`.

Regola sicurezza:
- Non usare alias `pending` negli ordini automatici.
- Non usare prodotti equivalenti se `allow_equivalent = false`.
- Se mancano pack/volume/peso necessari al confronto, escludere dall'ordinamento e mostrare warning.

---

## Fase 6 — API FastAPI

Aggiungere router `backend/app/api/v1/product_identity.py`.

Endpoint minimi:

```text
GET /api/v1/products
POST /api/v1/products
PATCH /api/v1/products/{product_id}

GET /api/v1/products/{product_id}/aliases
POST /api/v1/products/{product_id}/aliases
PATCH /api/v1/aliases/{alias_id}

GET /api/v1/match-candidates
POST /api/v1/match-candidates/{candidate_id}/approve
POST /api/v1/match-candidates/{candidate_id}/reject

POST /api/v1/orders/resolve-item
POST /api/v1/orders/optimize
```

### `POST /orders/resolve-item`

Request:

```json
{
  "query": "BICCHIERE CAFFE",
  "requested_qty": 10,
  "allow_equivalent": false,
  "location_id": null
}
```

Response: output di `resolve_order_item()`.

---

## Fase 7 — Frontend

### Nuovo componente: `ProductIdentityManager.tsx`

Funzioni:

1. lista prodotti interni;
2. crea/modifica prodotto interno;
3. mostra alias per fornitore;
4. approva/rifiuta candidati;
5. evidenzia campi mancanti: pack, volume, peso, comparison_unit.

### Aggiornare `OrderOptimizer.tsx`

Input tipo:

```text
BICCHIERE CAFFE, 10
ACQUA NATURALE 50CL, 20
COCA COLA 33CL LATTINA, 5
```

Output tabellare:

```text
Prodotto | Quantità | Migliore fornitore | Nome fornitore | Prezzo unitario normalizzato | Totale | Alternative | Warning
```

---

## Fase 8 — Seed iniziale categorie

Creare seed `backend/app/seed/product_identity_seed.py` con esempi:

```text
BICCHIERE_CAFFE
BICCHIERE_ACQUA
BICCHIERE_COCKTAIL
TOVAGLIOLO_40X40
CANNUCCIA_NERA
ACQUA_NATURALE_50CL_PET
COCA_COLA_33CL_LATTINA
```

Esempio prodotto:

```python
Product(
    sku_interno="BICCHIERE_CAFFE",
    canonical_name="Bicchiere caffè",
    normalized_name="bicchiere caffe",
    category="monouso",
    subcategory="bicchiere",
    volume_ml=80,
    comparison_unit="piece",
    is_commodity=True,
    is_active=True,
)
```

---

## Test obbligatori

### 1. Normalizzazione testo

```text
"BICCH. CAFFE 80CC X100" -> "bicchiere caffe 80 ml 100 pezzi"
"BICCHIERE CAFFE PZ 100" -> pack_qty = 100
"ACQUA 50 CL X24 PET" -> volume_ml = 500, pack_qty = 24, container_type = pet
```

### 2. Matching

```text
Alias approvato con stesso codice fornitore -> auto_match score 100
Alias approvato con stessa descrizione normalizzata -> auto_match score 98
Descrizione simile ma pack mancante -> needs_review
Brand diverso su prodotto branded -> parking/block_flag true
```

### 3. Prezzo normalizzato

```text
Bicchieri: 2.50€ x100 -> 0.025 €/piece
Acqua: 4.80€ x24 da 500ml -> 0.40 €/liter
Vino: 36€ x6 bottiglie -> 6 €/bottle
Caffè: 12€ x1kg -> 12 €/kg
```

### 4. Ordine

```text
Input: BICCHIERE CAFFE qty 10
Output: best_offer = fornitore con prezzo normalizzato più basso
```

### 5. Sicurezza

```text
Alias pending non usato negli ordini automatici
Prodotti equivalenti esclusi se allow_equivalent=false
Prodotti senza dati di normalizzazione esclusi dal ranking e mostrati come warning
```

---

## Definition of Done

La task è completa quando:

1. esistono/sono aggiornati i modelli `Product`, `SupplierProductAlias`, `ProductEquivalenceGroup`, `MatchCandidate`;
2. il matching crea candidati in Parking Area quando non è sicuro;
3. gli alias approvati vengono usati automaticamente;
4. il prezzo viene normalizzato correttamente per pezzo/litro/kg/bottiglia;
5. `POST /orders/resolve-item` restituisce il fornitore più conveniente;
6. `OrderOptimizer` usa il resolver e mostra alternative;
7. i test coprono normalizzazione, matching, prezzo e ordine;
8. il caso `BICCHIERE CAFFE` funziona end-to-end.
