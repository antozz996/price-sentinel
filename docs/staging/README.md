# PRICE SENTINEL V2 — Staging isolation plan

**Status: shared Hetzner staging containers deployed; private browser access is under configuration. Production V1 remains separate.**

This branch was cut from `feat/google-sheets-multisheet-dry-run`, which
itself depends on P0 branch `fix/smart-price-sheet-sync-p0`.
Draft PRs #2 and #3 remain unmerged; do not merge them implicitly.

## V1 stays operational

The production stack remains `docker-compose.yml` and its environment files
under `/etc/price-sentinel/`; the production frontend proxies `/api/*`
to the existing backend. Do not run or upgrade the production stack while
developing V2. A simple Vercel branch preview of the original `vercel.json`
could proxy to the LIVE backend and is NOT isolated.

The V2 branch intentionally removes that production API rewrite in `vercel.json`.
Until an independently secured staging API URL exists, the V2 frontend's
relative API calls will fail rather than reach V1. Do not copy production
rewrites into staging.

## Isolated staging scaffold

- Compose file: `docker-compose.v2-staging.yml` (not `docker-compose.yml`).
- Compose project name: `price_sentinel_v2`.
- PostgreSQL 15 database: `price_sentinel_v2_staging`.
- PostgreSQL app role: `ps_v2_app`.
- Network `v2_internal` has `internal: true`: no inbound ports AND
  **no outbound Internet**. The Google Sheets WIF read-only test continues
  separately in GitHub Actions. Network access to Google must be deliberately
  designed before direct V2 backend integration.
- Dedicated volume `price_sentinel_v2_v2_pgdata`, not production `pgdata`.
- Backend startup first runs `backend/scripts/ensure_v2_staging.py`.
  It aborts on wrong DB host/name/user, missing/placeholder secrets,
  debug mode, enabled automations, or non-staging environment.
- No production reverse proxy, no public V2 hostname, no webhook,
  no scheduled price sync. No production dataset copied.
- On the shared Hetzner host, V2's database and backend have been started
  in isolated containers; both reported `healthy`. The first web container
  was healthy internally but port publishing failed while it had only an
  `internal: true` network. The optional web overlay now adds a **web-only**
  `v2_ingress` bridge alongside `v2_internal`, and keeps host publishing
  strictly on `127.0.0.1:18084`. After pulling, ONLY recreate the web
  container and verify port bindings. Backend and DB must remain exclusively
  on `v2_internal`.
- V2 Vite production frontend build succeeded; access via SSH tunnel is
  next. Do not publicly expose a staging port or accept production webhooks.

**Shared VPS risk is accepted for this staging period, subject to monitoring.**
The user's server has 15 GiB RAM, 8 vCPU and approximately 63 GB free
at the last pre-deployment check. V2 container ceilings are DB 768 MB/0.75
CPU, backend 1500 MB/1.5 CPU and web 128 MB/0.25 CPU. These are container
limits, not a separate physical fault domain; avoid production disruption.

## Secret provisioning (when staging host is approved)

Template files ONLY (never live values):
- `docs/staging/postgres.env.example`
- `docs/staging/backend.env.example`

Create separate 0600 files under `/etc/price-sentinel-v2/` on the approved
staging host. Generate independent random secrets; never reuse V1 database
credentials, JWT signing secret, webhook key or bridge key. For a valid
`DATABASE_URL`, URL-encode reserved characters in the database password.
Never commit secrets or paste them into chat.

Do not run migrations, import invoices or enable ingress before reviewing
the staging deployment checklist. The FastAPI lifespan currently uses
`Base.metadata.create_all` on boot; therefore every staging start must
target only the V2 database, as enforced by the startup guard.

## CI test gate

`.github/workflows/v2-staging-safety.yml` runs on every push to
`staging/price-sentinel-v2` and checks:
1. startup guard permits only the staging database/configuration;
2. Compose network, ports and volumes are isolated;
3. Vercel config contains NO rewrite/redirect to production;
4. the browser API base stays relative;
5. repository data hygiene runs separately.

Passing these offline tests does not replace host-level checks. The
staging PostgreSQL/backend are running separately. Verify the new web-only
ingress explicitly with `docker port`, `curl`, and network inspection
after recreating ONLY the staging web container.

## Pending decisions / checkpoints

1. Shared Hetzner server selected and resources checked. Continue monitoring
   RAM, CPU and disk, and preserve V1 containers during V2 updates.
2. Confirm actual V1 frontend hosting: the currently connected Vercel team
   does not list a project linked to `antozz996/price-sentinel`.
   It may be another Vercel account/team or separately hosted.
3. For initial private testing, SSH tunnel to `127.0.0.1:18084` on the
   shared server. Validate loopback publication and private Nginx proxy to
   staging backend; DO NOT reconnect the V2 frontend to V1 API. A public
   hostname and TLS are deferred and require approval.
4. Confirm browser access via SSH tunnel, create a staging-specific test
   admin without default passwords, and execute E2E with synthetic test
   data only. Staging DB was initialized to 56 tables.
5. Import P0/P1 features into the staging app (already present in branch),
   test full API flows, mapping and approvals; disable all automatic commits
   until the product owner signs off.
6. Verify rollback/backup, production database untouched, and then request
   explicit separate approval before any production deployment or merge.

## Code links

Branch: `staging/price-sentinel-v2`.

Google Sheets WIF live dry-run already passed in a separate feature branch,
reading 1,897 candidate quotes and committing zero prices. That success
does not certify the future V2 staging deployment.
