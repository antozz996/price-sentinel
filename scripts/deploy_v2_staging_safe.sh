#!/usr/bin/env bash
# Safe, gated shared-VPS redeploy of Price Sentinel V2 staging ONLY.
# Usage:
#   bash /opt/price-sentinel-v2/scripts/deploy_v2_staging_safe.sh <tested_git_sha>
# Does NOT use /root/PRICE SENTINEL, production Compose, production credentials,
# production DB volumes, external ports, automatic jobs or real supplier data.
set -Eeuo pipefail

ROOT=/opt/price-sentinel-v2
BRANCH=staging/price-sentinel-v2
EXPECTED_SHA="${1:-}"
PROJECT=price_sentinel_v2
COMPOSE=(docker compose -p "$PROJECT" \
  -f "$ROOT/docker-compose.v2-staging.yml" \
  -f "$ROOT/docker-compose.v2-staging-web.yml")

fail() { echo "STOP: $*" >&2; exit 1; }
trap 'echo "STOP: V2-only deployment did not complete. Check the last error; V1 was not targeted." >&2' ERR

[[ -n "$EXPECTED_SHA" && "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "Provide an approved 40-character V2 commit SHA"
[[ -d "$ROOT/.git" ]] || fail "Expected separate staging checkout missing"
[[ "$(git -C "$ROOT" branch --show-current)" == "$BRANCH" ]] || fail "Not on the V2 staging branch"
[[ "$(git -C "$ROOT" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "Checkout SHA differs from the tested staging SHA"
git -C "$ROOT" remote get-url origin | grep -Eq '^((https://github\.com/)|(git@github\.com:))antozz996/price-sentinel(\.git)?$' \
  || fail "Unexpected Git origin"
git -C "$ROOT" diff --quiet || fail "Staging checkout has uncommitted tracked changes"
git -C "$ROOT" diff --cached --quiet || fail "Staging checkout has staged changes"
[[ -s "$ROOT/frontend/package-lock.json" ]] || fail "Missing frontend package lock"
[[ -f /etc/price-sentinel-v2/backend.env && -f /etc/price-sentinel-v2/postgres.env ]] \
  || fail "Separate V2 env files not found"

for name in ps_backend ps_db price_sentinel_v2-db-1 price_sentinel_v2-backend-1 price_sentinel_v2-web-1; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$name")" == healthy ]] \
    || fail "Container $name is not healthy; no update attempted"
done
echo "PASS: both V1 and V2 backends/databases are healthy"

# Pure validation; do not print resolved Compose configuration or secrets.
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" config --format json | python3 -c '
import json, sys
d=json.load(sys.stdin)
s=d["services"]
assert set(s)=={"db","backend","web"}
assert s["db"]["networks"]==["v2_internal"]
assert s["backend"]["networks"]==["v2_internal"]
assert s["web"]["networks"]==["v2_internal","v2_ingress"]
assert d["networks"]["v2_internal"]["internal"] is True
assert all(p["host_ip"]=="127.0.0.1" and str(p["published"])=="18084" and p["target"]==80 for p in s["web"]["ports"])
assert not s["db"].get("ports") and not s["backend"].get("ports")
assert str(s["backend"]["environment"]["AUTOMATION_ENABLED"]).lower() in ("false","0")
assert str(s["backend"]["environment"]["ENVIRONMENT"]).lower()=="staging"
print("PASS: V2 isolated Compose and loopback-only ingress")
'
[[ "$(docker port price_sentinel_v2-web-1 80/tcp)" == "127.0.0.1:18084" ]] \
  || fail "Existing staging web is not loopback-only"

python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit
base = Path("/etc/price-sentinel-v2")
def load(filename):
    return dict(line.split("=",1) for line in (base/filename).read_text().splitlines()
                if "=" in line and not line.startswith("#"))
db = load("postgres.env")
app = load("backend.env")
u = urlsplit(app["DATABASE_URL"])
assert u.hostname == "db" and u.path == "/price_sentinel_v2_staging"
assert u.username == db["POSTGRES_USER"] == "ps_v2_app"
assert u.password == db["POSTGRES_PASSWORD"]
assert app["ENVIRONMENT"] == "staging"
assert app["DEBUG"] == "false"
assert app["AUTOMATION_ENABLED"] == "false"
print("PASS: independent V2 database credentials validated")
PY

available_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
[[ "$available_kb" -ge 2097152 ]] || fail "Available RAM below 2 GiB"
disk_avail_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
[[ "$disk_avail_kb" -ge 8388608 ]] || fail "Available disk below 8 GiB"

# Preserve the old V2 frontend and backend image for manual rollback.
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ROLLBACK=/opt/price-sentinel-v2-rollback/"$STAMP"
mkdir -p "$ROLLBACK"
cp -a "$ROOT/frontend/dist" "$ROLLBACK/frontend-dist"
OLD_IMAGE=$(docker inspect -f '{{.Image}}' price_sentinel_v2-backend-1)
ROLLBACK_TAG="price-sentinel-v2-backend:rollback-$STAMP"
docker tag "$OLD_IMAGE" "$ROLLBACK_TAG"
echo "PASS: V2 rollback assets captured at $ROLLBACK"

echo "Building ONLY V2 frontend in a temporary limited Node container..."
docker run --rm --cpus=1.5 --memory=1536m \
  -v "$ROOT/frontend:/work" -w /work node:22-bookworm-slim \
  sh -lc 'npm ci --no-audit --no-fund && npm run build'
[[ -s "$ROOT/frontend/dist/index.html" ]] || fail "V2 frontend build missing"

echo "Rebuilding and recreating ONLY V2 backend..."
"${COMPOSE[@]}" up -d --no-deps --build --force-recreate --wait --wait-timeout 180 backend

echo "Recreating ONLY V2 web container..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 120 web

[[ "$(docker port price_sentinel_v2-web-1 80/tcp)" == "127.0.0.1:18084" ]] \
  || fail "Web no longer loopback-only"
curl --fail --silent --show-error --max-time 12 \
  http://127.0.0.1:18084/api/v1/health | python3 -c '
import sys,json
data=json.load(sys.stdin)
assert data["status"]=="healthy" and data["environment"]=="staging"
print("PASS: V2 web proxy targets staging API")
'
curl --fail --silent --show-error --max-time 12 \
  http://127.0.0.1:18084/ -o /dev/null

echo "Running staging authenticated, GET-only smoke suite..."
docker exec price_sentinel_v2-backend-1 python -m scripts.smoke_v2_staging

for name in ps_backend ps_db price_sentinel_v2-db-1 price_sentinel_v2-backend-1 price_sentinel_v2-web-1; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$name")" == healthy ]] \
    || fail "Post-deploy health check failed for $name"
done
echo "PASS: Price Sentinel V2 redeployed, smoke tests green, V1 still healthy."
echo "Rollback backups remain at: $ROLLBACK (V2 ONLY)"
