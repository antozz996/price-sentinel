# 🛸 PRICE SENTINEL — Master AI Handoff & Project Status

> **ATTENTION FOR INCOMING AI AGENTS:** This file is the primary source of truth for the project state. Read this **entirely** before writing a single line of code. It documents architecture, what is done, what is pending, and how to resume safely.

---

## 📋 Project Identity

| Field | Value |
|-------|-------|
| **Project Name** | Price Sentinel |
| **Objective** | Automated purchase audit system for a Ho.Re.Ca. multi-location group. Matches Electronic Invoices (FatturaPA / Aruba Webhook) against Master Price Lists to detect anomalies and track "Recovered Funds" via Credit Notes. |
| **Last Updated** | 2026-05-15 |
| **Current Milestone** | **Sprint 3 COMPLETE** — Full-stack dashboard deployed, Fatture module live, Intelligence API active. |

---

## 🏗️ Technical Architecture

### 1. Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| `ps_db` | PostgreSQL 15-alpine | Internal network only (`ps_internal`) |
| `ps_backend` | FastAPI / Python 3.11-slim | Async SQLAlchemy + Alembic; hot-reload via Uvicorn |
| `ps_nginx` | Nginx | SSL termination, reverse proxy, rate limiting; self-signed certs in `nginx/ssl/` |
| **Frontend** | React + TypeScript + Vite | Deployed on **Vercel** (CDN), communicates with backend via `vercel.json` rewrite rules |

**Backend host (production):** `http://46.225.81.66` (raw server IP — Nginx listens on 80/443)
**Frontend URL:** Deployed via Vercel; `vercel.json` proxies `/api/*` → `http://46.225.81.66/api/*`

### 2. Backend Stack

- **Framework:** FastAPI (async)
- **DB Layer:** SQLAlchemy (AsyncSession) + Alembic migrations
- **Auth:** JWT (`python-jose`) + Bcrypt (`passlib`) — Bearer token, role + location claims
- **Validation:** Pydantic v2
- **Ingestion:** Webhook-based (Aruba API Key validation) + Manual XML/ZIP upload endpoint

### 3. Frontend Stack

- **Framework:** React 18 + TypeScript + Vite
- **Styling:** Vanilla CSS (dark glassmorphism design system in `index.css`)
- **No routing library** — single-page tab-based navigation in `App.tsx`
- **Auth:** Auto-login with hardcoded admin credentials in `App.tsx` (dev mode — JWT stored in `localStorage`)
- **API layer:** `src/api.ts` — exports `API_BASE` constant

---

## 📂 Project Structure Map

```text
/root/PRICE SENTINEL/
├── backend/
│   ├── alembic/                  # DB Migrations
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── router.py         # Aggregates all routers under /api/v1
│   │   │       ├── auth.py           # POST /auth/login → JWT
│   │   │       ├── utenti.py         # User management
│   │   │       ├── location.py       # GET/POST /location/
│   │   │       ├── fornitori.py      # GET/POST /fornitori/
│   │   │       ├── listino.py        # Excel import + versioning
│   │   │       ├── fatture.py        # ⭐ Fatture list + marker PATCH + righe
│   │   │       ├── anomalie.py       # 7-state workflow CRUD
│   │   │       ├── alias.py          # Alias product mapping
│   │   │       ├── webhook.py        # POST /webhook/aruba (Aruba API Key)
│   │   │       ├── ingestion.py      # ⭐ POST /ingestion/manual (XML/ZIP upload)
│   │   │       └── intelligence.py   # ⭐ KPI aggregates, cross-location stats
│   │   ├── models/
│   │   │   ├── __init__.py           # Exports all models (critical for Alembic)
│   │   │   ├── fatture.py            # Fattura, RigaFattura, MarkerFattura enum
│   │   │   ├── anomalie.py           # Anomalia + 7-state enum
│   │   │   ├── listino.py            # ListinoMaster (append-only versioning)
│   │   │   ├── alias.py              # AliasFornitore
│   │   │   ├── fornitori.py          # Fornitore
│   │   │   ├── location.py           # Location (field: nome_struttura ← CRITICAL)
│   │   │   └── utenti.py             # Utente + RuoloUtente enum
│   │   ├── schemas/
│   │   │   └── fatture.py            # FatturaResponse, RigaFatturaResponse
│   │   ├── services/
│   │   │   ├── auth.py               # JWT + bcrypt helpers
│   │   │   ├── xml_parser.py         # Namespace-agnostic FatturaPA parser
│   │   │   ├── matching.py           # 4-level match engine
│   │   │   ├── ingestion.py          # TD01/TD04/TD08 pipeline orchestrator
│   │   │   ├── excel_import.py       # Template gen + .xlsx parser
│   │   │   ├── test_e2e.py           # Headless E2E test script
│   │   │   └── seed.py               # Dev data population
│   │   ├── main.py                   # FastAPI app factory
│   │   ├── database.py               # AsyncSession factory + get_db dependency
│   │   └── config.py                 # Pydantic Settings (reads .env)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api.ts                    # API_BASE constant
│   │   ├── main.tsx                  # React entry point
│   │   ├── index.css                 # Global dark glassmorphism design system
│   │   ├── App.tsx                   # ⭐ Tab navigation + auto-login
│   │   └── components/
│   │       ├── Dashboard.tsx         # KPI overview (calls /intelligence/)
│   │       ├── ManualUpload.tsx      # ⭐ XML/ZIP drag-drop uploader
│   │       ├── FattureList.tsx       # ⭐ Fatture table + filters + marker + righe
│   │       ├── ValidationRoom.tsx    # Anomalie workflow (7 states)
│   │       ├── PriceListManager.tsx  # Listino import + versioning UI
│   │       └── SettingsPage.tsx      # Config + user management
│   ├── package.json
│   └── vite.config.ts
├── nginx/
│   ├── nginx.conf
│   └── ssl/                          # fullchain.pem, privkey.pem
├── vercel.json                       # ⭐ Vercel build config + /api/* proxy
├── docker-compose.yml
├── .env                              # Active dev environment (secrets)
└── PRICE_SENTINEL_MASTER_HANDOFF.md  # ← THIS FILE
```

---

## ⚠️ Critical Gotchas (Read Before Touching Code)

1. **`Location.nome_struttura` NOT `Location.nome`** — The SQLAlchemy model uses `nome_struttura` as the column name. The frontend `FattureList.tsx` expects `location_nome` as a label from the query join. Any AI that uses `.nome` will get a silent `None`.
2. **`MarkerFattura` is a Python Enum** — When serializing `marker` in API responses, always use `.value` (e.g. `r.marker.value if hasattr(r.marker, 'value') else r.marker`). Raw enum object will cause Pydantic/JSON serialization failures.
3. **Frontend auto-login is hardcoded** — `App.tsx` auto-authenticates as `admin@pricesentinel.it` / `admin2025!`. This is intentional for the internal admin dashboard. Do NOT add a login page without discussing with the user.
4. **Vercel proxy rewrites** — `vercel.json` rewrites `/api/:path*` to the raw server IP. If the backend IP changes, update `vercel.json`.
5. **No React Router** — Navigation is purely tab-based state in `App.tsx`. Do NOT introduce React Router unless explicitly requested.
6. **`bypass-tunnel-reminder: true` header** — Required on all fetch calls in the frontend to avoid Cloudflare/tunnel interference. Already set in all components via the `headers` object.

---

## 📍 Current State — What Is Done vs. Pending

### ✅ Sprint 1: Foundation + Listino Import (COMPLETE)
- Multi-container Docker setup (`ps_db`, `ps_backend`, `ps_nginx`) — all healthy
- 12-table schema: `ListinoMaster`, `Anomalie`, `XMLRaw`, `Fattura`, `RigaFattura`, `Fornitore`, `Location`, `Utente`, `Alias`, etc.
- JWT Auth system — login, role/location claims, dependency injection
- Excel Import Engine: template download (`GET /listino/template-excel`) + bulk import (`POST /listino/import-excel/{fornitore_id}`) with dry-run mode
- Listino versioning: Append-Only (`POST /{id}/aggiorna-prezzo`) with auto-expiry of old records
- Seed script: admin + manager users, 3 locations, 2 suppliers, 5 listino items

### ✅ Sprint 2: XML Parser & Matching Engine (COMPLETE)
- XML Parser (`xml_parser.py`): namespace-agnostic, handles `DettaglioLinee`, multiple `Sconti/Maggiorazioni`, Omaggio detection, net price normalization
- Matching Engine (`matching.py`): 4 levels — L1 Alias Esatti, L2 EAN Barcodes, L3 Fuzzy (SequenceMatcher >65%), L4 Parking Area fallback
- Ingestion Pipeline (`ingestion.py`): TD01/TD04/TD08 routing, creates `Fattura` + `RigaFattura` + `Anomalia` records
- Webhook (`/webhook/aruba`): Aruba API Key validation, Base64 payload, SHA-256 idempotency, full pipeline triggered synchronously

### ✅ Sprint 3: Dashboard UI + Fatture Module (COMPLETE)
- **Frontend**: React + TypeScript + Vite — full dark glassmorphism UI deployed on Vercel
- **`App.tsx`**: Tab navigation (Dashboard, Carica Fatture, Registro Fatture, Validazione, Listini Master, Settings) + JWT auto-login
- **`FattureList.tsx`** ⭐: Full fatture list with advanced filtering (fornitore, location, marker, date range, doc search), marker management dropdown (6 states: nessuno/da_verificare/verificata/contestata/approvata/sospesa), expandable row detail with `RigaFattura` breakdown + matching status badges
- **`ManualUpload.tsx`** ⭐: Drag-and-drop XML/ZIP uploader → `POST /ingestion/manual`
- **`PriceListManager.tsx`**: Listino import UI + template download
- **`ValidationRoom.tsx`**: Anomalie workflow viewer (7 states)
- **`SettingsPage.tsx`**: Config + user management
- **`intelligence.py`** ⭐: KPI aggregation router — `/intelligence/` endpoints for cross-location stats
- **`ingestion.py` API** ⭐: `POST /ingestion/manual` — multipart XML/ZIP upload endpoint
- **`vercel.json`** ⭐: Vercel build config — `cd frontend && npm install && npm run build`, output `frontend/dist`, `/api/*` → `http://46.225.81.66/api/*`

### 🚧 Sprint 4: Pending
- **Telegram Notifications**: Alert on anomaly creation (bot + chat_id in `.env`)
- **Admin Dashboard**: Cross-location comparison table, Vendor Passport PDF generation
- **Anomalie Workflow UI**: Full state machine transitions in `ValidationRoom.tsx` (currently read-only)
- **Real Login Page**: Proper login form replacing the hardcoded auto-login (for multi-user deployment)
- **Credit Note Auto-Matching**: TD04 documents automatically linked to original TD01 `Fattura`

---

## 🔌 API Reference (v1)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/v1/auth/login` | None | Email + password → JWT |
| GET | `/api/v1/fatture/` | Bearer | List fatture with filters (location_id, fornitore_id, marker, data_da, data_a, search, limit, offset) |
| PATCH | `/api/v1/fatture/{id}/marker` | Bearer | Update fattura marker (query param `marker=`) |
| GET | `/api/v1/fatture/{id}` | Bearer | Fattura detail |
| GET | `/api/v1/fatture/{id}/righe` | Bearer | Line items of a fattura |
| GET | `/api/v1/anomalie/` | Bearer | List anomalie with filters |
| PATCH | `/api/v1/anomalie/{id}/stato` | Bearer | Change anomaly state |
| POST | `/api/v1/webhook/aruba` | ApiKey | Aruba webhook → full ingestion pipeline |
| POST | `/api/v1/ingestion/manual` | Bearer | Manual XML/ZIP file upload → full ingestion pipeline |
| GET | `/api/v1/listino/template-excel` | Bearer | Download .xlsx template |
| POST | `/api/v1/listino/import-excel/{fornitore_id}` | Bearer | Bulk import listino from .xlsx |
| GET | `/api/v1/intelligence/` | Bearer | KPI aggregates + cross-location stats |
| GET | `/api/v1/location/` | Bearer | List locations |
| GET | `/api/v1/fornitori/` | Bearer | List fornitori |

---

## 🔑 Dev Credentials (Local Only)

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@pricesentinel.it | admin2025! |
| Manager | manager.playa@pricesentinel.it | manager2025! |

---

## 🛠️ Instructions for Resuming Work

### Backend (Docker)
```bash
# Start all services
cd "/root/PRICE SENTINEL"
docker-compose up -d

# Run DB migrations
docker-compose exec -T backend alembic upgrade head

# Populate dev data
docker-compose exec -T backend python -m app.services.seed

# Test health
curl https://localhost/api/v1/health -k

# Test login
curl -k -X POST https://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@pricesentinel.it","password":"admin2025!"}'
```

### Frontend (Local Dev)
```bash
cd "/root/PRICE SENTINEL/frontend"
npm install
npm run dev  # runs on http://localhost:5173
```

### Frontend (Production Deploy)
Vercel auto-deploys on push. Manual trigger:
```bash
cd "/root/PRICE SENTINEL"
vercel --prod  # uses vercel.json config
```

---

## 📝 Change Log

### [2026-05-15] Bug Fix: Registry Invoices & Location Naming ✅
- Corretto mismatch di naming tra Backend (`nome_struttura`) e Frontend (`nome`) che impediva il corretto funzionamento dei filtri e delle etichette nel Registro Fatture.
- Implementata gestione degli errori API nel `FattureList` per evitare schermate vuote silenziose in caso di problemi di rete o autenticazione.
- Verificato il corretto caricamento dei dati tramite test E2E.

### [2026-05-15] System Operational Check ✅
- Eseguito un test completo dell'ambiente: container Docker avviati, migrazioni DB allineate, seed del database verificato.
- Test degli endpoint API (`/health` e `/login`) passati con successo.
- Frontend React compilato senza errori (`vite build`). Il sistema è stabile e 100% operativo.

### [2026-05-15] Sprint 3: Full-Stack Dashboard ✅
- **Frontend (Vite/React)**: Built complete dark glassmorphism dashboard with 6 navigation tabs.
- **`FattureList.tsx`**: Advanced fatture table with multi-filter support, marker dropdown management (6 states), expandable line-item detail with matching status badges.
- **`ManualUpload.tsx`**: Drag-and-drop XML/ZIP upload UI calling `POST /ingestion/manual`.
- **`fatture.py` (API)**: Full read router with JOIN aggregation (`n_righe`, `n_anomalie`, `fornitore_nome`, `location_nome`), marker PATCH, righe sub-endpoint. Role-based access: manager sees only own location.
- **`ingestion.py` (API)**: Manual multipart upload endpoint wrapping the existing ingestion pipeline.
- **`intelligence.py` (API)**: KPI aggregation endpoints for the Overview Dashboard.
- **`router.py`**: Registered `ingestion` and `intelligence` routers.
- **`vercel.json`**: Configured Vercel deployment with API proxy rewrite to `http://46.225.81.66`.

### [2026-04-16] Sprint 2: XML Parser & Matching Engine ✅
- `xml_parser.py`: Namespace-agnostic FatturaPA tree extraction, Omaggi detection, net price normalization.
- `matching.py`: 4-level engine (Alias → EAN → Fuzzy >65% → Parking Area).
- `ingestion.py` (service): TD01/TD04/TD08 orchestrator generating `Anomalia` records if delta > 0.
- `webhook.py`: Aruba webhook triggers full pipeline on Base64 payload.
- `test_e2e.py`: Headless E2E validation script.

### [2026-04-16] Sprint 1: Foundation + Listino Import ✅
- Docker Compose v2.4 setup with health checks.
- 12-table schema + Alembic migrations (v2).
- JWT auth system (login tested, returns valid token).
- Excel import engine: template gen + bulk import with dry-run, per-row validation.
- Seed script: admin/manager/locations/suppliers/listino items.
- Dependency: `openpyxl==3.1.5`.

### [2026-04-15] Milestone 0: Core Foundation ✅
- Docker Compose, PostgreSQL 15, Nginx SSL, `.env`.
- 12 primary tables + `alembic_version` confirmed via `psql`.
- Webhook Aruba with SHA-256 idempotency.
- `/api/v1/health` returning 200 via HTTPS.
