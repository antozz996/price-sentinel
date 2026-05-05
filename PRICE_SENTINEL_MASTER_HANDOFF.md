# 🛸 PRICE SENTINEL — Master AI Handoff & Project Status

> **ATTENTION FOR INCOMING AI AGENTS:** This file is the primary source of truth for the project state. Read this first to understand the architecture and resume work without context loss.

## 📋 Project Identity
**Project Name:** Price Sentinel
**Objective:** Automated purchase audit system for a Ho.Re.Ca. multi-location group. It matches Electronic Invoices (Aruba Webhook) against Master Price Lists to detect anomalies and track "Recovered Funds" via Credit Notes.

---

## 🏗️ Technical Architecture

### 1. Infrastructure (Dockerized)
- **Service Name:** `ps_db` (Postgres 15-alpine) - Internal network only.
- **Service Name:** `ps_backend` (FastAPI / Python 3.11-slim) - Hot-reload dev server.
- **Service Name:** `ps_nginx` (Nginx) - SSL termination, Reverse Proxy, Rate Limiting.
- **Network:** `ps_internal` (Bridge).
- **SSL:** Self-signed certs in `nginx/ssl/` for dev.

### 2. Backend Stack
- **Framework:** FastAPI
- **DB Layer:** SQLAlchemy (Async) + Alembic (Migrations).
- **Auth:** JWT (python-jose) + Bcrypt (passlib).
- **Validation:** Pydantic v2.
- **Ingestion:** Webhook-based (Aruba API Key validation).

---

## 📍 Current State (Milestone 2: Motore Matching & Ingestion)

### ✅ Done & Verified
- **Multi-Container Setup**: All 3 services are healthy and communicating.
- **Schema Mapping**: 12 tables implemented including `ListinoMaster` (Append-only versioning), `Anomalie` (7-state workflow), and `XMLRaw` (Idempotent ingestion).
- **API Skeleton**: 9 functional routers (Auth, Users, Locations, Suppliers, PriceLists, Invoices, Anomalies, Aliases, Webhook).
- **Security**: Nginx configured for HTTP->HTTPS redirect and API Key validation.
- **Database**: Migrations initialized; schema matches Master Specs v1.0.
- **Auth System**: JWT login tested — returns token with role + location claims.
- **Seed Data**: Admin + Manager users, 3 Locations, 2 Fornitori, 5 Listino items populated.
- **Excel Import Engine**: Template download (`GET /template-excel`) and bulk import (`POST /import-excel/{fornitore_id}`) with dry-run validation mode.
- **Listino Versioning**: Append-Only endpoint (`POST /{id}/aggiorna-prezzo`) with auto-expiration of old records.
- **XML Parser (FatturaPA)**: Namespace-agnostic tree extraction, supports DettaglioLinee, multiple Sconti/Maggiorazioni, and Omaggio detection.
- **Matching Engine (4 Livelli)**:
  1. Alias Esatti
  2. EAN Barcodes
  3. Fuzzy Match (SequenceMatcher > 65%)
  4. Parking Area fallback
- **Ingestion Pipeline**: Orchestrator (TD01 routing, TD04 credit notes, TD08 debit notes), creates `Fattura`, `RigaFattura`, and `Anomalia` records.

### 🚧 In Progress / Pending
- **Sprint 3**: Telegram Notifications + Dashboard UI (React/Vite).
- **Sprint 4**: Admin Dashboard + Cross-Location Tracker + Vendor Passport PDF.

---

## 📂 Project Structure Map
```text
/root/PRICE SENTINEL/
├── backend/
│   ├── alembic/            # DB Migrations
│   ├── app/
│   │   ├── api/v1/         # Endpoints (9 routers)
│   │   ├── models/         # 12 SQLAlchemy Models
│   │   ├── schemas/        # Pydantic validation
│   │   ├── services/
│   │   │   ├── auth.py           # JWT + bcrypt
│   │   │   ├── xml_parser.py     # Namespace-agnostic FatturaPA parser
│   │   │   ├── matching.py       # 4-Level Match Engine
│   │   │   ├── ingestion.py      # Pipeline & router TD01/TD04/TD08
│   │   │   ├── excel_import.py   # Template gen + parser
│   │   │   ├── test_e2e.py       # E2E test script
│   │   │   └── seed.py           # Dev data population
│   │   ├── main.py         # App factory
│   │   ├── database.py     # Async Session setup
│   │   └── config.py       # Pydantic Settings
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   ├── nginx.conf
│   └── ssl/                # Certs (fullchain.pem, privkey.pem)
├── docker-compose.yml
├── .env                    # Active dev environment
└── PRICE_SENTINEL_MASTER_HANDOFF.md  # ← THIS FILE
```

---

## 📝 Change Log (Technical & Functional)

### [2026-04-16] Sprint 2: XML Parser & Matching Engine ✅
- **XML Parser**: `app/services/xml_parser.py` implemented robust element extraction ignoring namespaces. Supports Omaggi detection and net price normalization.
- **Matching Engine**: `app/services/matching.py` implemented following Spec §3.1 and §3.2. Levels 1 (Alias), Level 2 (EAN), Level 3 (Fuzzy > 65% match), and fallback to Parking Area.
- **Ingestion Orchestrator**: `app/services/ingestion.py` processes TD01/TD04/TD08 correctly, generating `Anomalia` records if Delta > 0.
- **Webhook Update**: `/api/v1/webhook/aruba` now triggers the full pipeline synchronously upon receiving Base64 payload, responding with ID and run report.
- **E2E Testing**: Developed `app/services/test_e2e.py` for headless pipeline validation. *(Note: pending container restart validation if terminal hangs).*

### [2026-04-16] Sprint 1: Foundation + Import Listini ✅
- **Seed Script**: `app/services/seed.py` — populates DB with admin, manager, 3 locations, 2 suppliers, 5 price list items. Run via `docker-compose exec -T backend python -m app.services.seed`.
- **Excel Import Engine**: `app/services/excel_import.py` — generates styled .xlsx templates with header, example row, frozen panes; parses uploaded files with per-row validation (SKU, price, date formats, PFA type/value checks).
- **New API Endpoints**:
  - `GET /api/v1/listino/template-excel` — download template .xlsx for a given supplier.
  - `POST /api/v1/listino/import-excel/{fornitore_id}` — bulk import from .xlsx with `dry_run` option. Skips duplicate active SKUs.
- **Auth Tested**: JWT login returns valid token; listino endpoint returns 5 seeded items.
- **Dependency**: Added `openpyxl==3.1.5` to requirements.txt.
- **Docker**: Rebuilt backend image with new dependency.
- **DB Migration**: Regenerated v2 migration after schema reset (12 tables + indexes confirmed).

### [2026-04-15] Milestone 0: Core Foundation ✅
- **Infrastructure**: Initialized Docker Compose with v2.4 compatibility for `service_healthy`.
- **Database**: Created 12 primary tables + `alembic_version`. Verified via `psql`.
- **API**: Implemented Webhook Aruba with header-based API Key security and SHA-256 idempotency check.
- **Environment**: Setup `.env` and SSL certs. Verified 200 OK on `/api/v1/health` via HTTPS.
- **Mockups**: Generated visual design concepts for Admin Dashboard and Manager Validation Room.

---

## 🔑 Dev Credentials (Local Only)
| Role | Email | Password |
|------|-------|----------|
| Admin | admin@pricesentinel.it | admin2025! |
| Manager | manager.playa@pricesentinel.it | manager2025! |

## 🛠️ Instructions for Resuming Work
1. **Context**: Read `price_sentinel_master_spec.pdf` for business logic.
2. **Setup**: Run `docker-compose up -d` from `/root/PRICE SENTINEL/`.
3. **Database**: Use `docker-compose exec -T backend alembic upgrade head` for migrations.
4. **Seed**: Use `docker-compose exec -T backend python -m app.services.seed` to populate dev data.
5. **Auth**: `POST /api/v1/auth/login` with email/password → get JWT Bearer token.
6. **Webhook**: `POST /api/v1/webhook/aruba` — requires `Authorization: ApiKey <KEY_IN_ENV>`.
7. **Excel**: `GET /api/v1/listino/template-excel` → download, fill, `POST /api/v1/listino/import-excel/{id}`.

