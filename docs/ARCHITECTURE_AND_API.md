# Price Sentinel — architettura e API operative

## Confini del sistema

Price Sentinel importa e conserva le fatture, analizza prezzi e anomalie e riconcilia
manualmente ordini LiquidStock, ricezioni e documenti fiscali. LiquidStock resta il
sistema autorevole per ordini e ricezioni; Price Sentinel resta autorevole per fatture,
contestazioni e recuperi economici.

L'integrazione non modifica mai `products.current_stock` in LiquidStock. Nessun nome,
prezzo, quantità o unità viene associato definitivamente con logica fuzzy. Le proposte
richiedono una conferma umana.

## Componenti

- React/Vite: portale operatore.
- FastAPI: API private `/api/v1`.
- PostgreSQL/Alembic: dati applicativi e migrazioni.
- Nginx dietro Caddy: contenuti statici, reverse proxy e rate limiting.
- Bridge LiquidStock: riceve eventi firmati e idempotenti nella inbox.
- Monitor operativo: genera avvisi deduplicati senza compiere azioni economiche.

## Flusso ordine-fattura

1. LiquidStock registra un evento nella propria outbox.
2. Il dispatcher invia l'evento firmato al bridge Price Sentinel.
3. Price Sentinel conserva ordine, righe, ricezioni e snapshot originali.
4. L'operatore associa esplicitamente venue, fornitore e prodotti.
5. Una fattura candidata è solo un suggerimento; l'associazione è manuale.
6. La riconciliazione confronta quantità e prezzi usando le soglie della sede.
7. Le anomalie possono essere raccolte in una contestazione.
8. Comunicazioni, risposte, allegati e note di credito sono versionati e tracciati.

## Contestazioni

Le entità principali sono:

- `dispute_cases`: pratica, importo richiesto/riconosciuto/recuperato e stato;
- `dispute_case_anomalies`: anomalie selezionate, con una sola fonte valida;
- `dispute_communications`: versioni immutabili del testo e hash;
- `dispute_supplier_responses`: risposte fornitore;
- `dispute_attachments`: metadati e contenuto allegato;
- `dispute_credit_notes` e `dispute_credit_note_allocations`: note TD04 e allocazioni;
- `dispute_audit_events`: audit append-only.

Stati: `draft`, `ready_to_send`, `sent`, `supplier_replied`,
`credit_note_expected`, `partially_recovered`, `recovered`, `rejected`, `closed`,
`cancelled`. Le transizioni terminali richiedono una motivazione e non sono riaperte
implicitamente.

## API aggiunte

Tutte le rotte richiedono JWT, salvo le rotte pubbliche già documentate dal progetto.
Gli utenti manager sono limitati alla propria sede; gli admin possono operare su tutte
le sedi autorizzate dal modello applicativo.

- `GET /api/v1/disputes/candidates`
- `GET /api/v1/disputes/dashboard`
- `GET|POST /api/v1/disputes`
- `GET|PATCH /api/v1/disputes/{case_id}`
- `POST /api/v1/disputes/{case_id}/transition`
- `POST /api/v1/disputes/{case_id}/recognition`
- `POST /api/v1/disputes/{case_id}/communications/prepare`
- `POST /api/v1/disputes/{case_id}/communications/{id}/events`
- `POST /api/v1/disputes/{case_id}/responses`
- `POST /api/v1/disputes/{case_id}/attachments`
- `GET /api/v1/disputes/{case_id}/attachments/{attachment_id}`
- `POST /api/v1/disputes/{case_id}/credit-notes`
- `GET /api/v1/disputes/{case_id}/pdf`
- `GET /api/v1/automation/alerts`
- `POST /api/v1/automation/alerts/{id}/acknowledge`
- `POST /api/v1/automation/run` (admin)
- `GET /api/v1/automation/runs`
- `GET /api/v1/onboarding/locations/{id}/readiness`
- `GET|PUT /api/v1/onboarding/locations/{id}/settings`
- `GET /api/v1/auth/me`

La documentazione OpenAPI esposta dall'istanza è la fonte puntuale per payload e codici
di risposta.

## Automazioni

Il monitor rileva riconciliazioni ferme, fatture candidate, anomalie importanti,
contestazioni in scadenza, note di credito mancanti ed eventi LiquidStock falliti.
Gli alert sono idempotenti e deduplicati. Il monitor non associa fatture, non modifica
prezzi, non genera note di credito e non chiude contestazioni.

L'esecuzione periodica è controllata da:

- `AUTOMATION_ENABLED` (predefinito `false`);
- `AUTOMATION_INTERVAL_SECONDS` (minimo 60, predefinito 900).

## Sicurezza

- JWT verificato dal backend e autorizzazione per sede a ogni operazione.
- Snapshot e audit economici append-only.
- Optimistic locking sulle contestazioni.
- Upload massimo 10 MB con allowlist dei content type.
- Login, API e webhook protetti da rate limit Nginx.
- Segreti forniti solo tramite ambiente; nessun segreto deve entrare in Git.
- Migrazioni e rollback sono separati e testati su database usa-e-getta.
