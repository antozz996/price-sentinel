"""Read-only authenticated API smoke checks for the isolated V2 staging app.

Run only inside the running V2 backend container after a guarded redeploy:
    docker exec price_sentinel_v2-backend-1 python -m scripts.smoke_v2_staging

No credentials, JWTs, or returned business data are printed. Does not call
POST/PUT/PATCH/DELETE endpoints, import data, or enable automation.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.utenti import RuoloUtente, Utente
from app.services.auth import create_access_token
from scripts.ensure_v2_staging import validate


GET_PROBES: tuple[tuple[str, str], ...] = (
    ("Sessione", "/api/v1/auth/me"),
    ("Impostazioni aziendali", "/api/v1/settings/company/"),
    ("Sedi", "/api/v1/location/"),
    ("Fornitori", "/api/v1/fornitori/"),
    ("Categorie e fornitori", "/api/v1/categories/matrix"),
    ("Sottocategorie", "/api/v1/categories/subcategories"),
    ("Listini", "/api/v1/listino/?limit=5"),
    ("Fatture", "/api/v1/fatture/?limit=5"),
    ("Anomalie", "/api/v1/anomalie/?limit=5"),
    ("Ordini", "/api/v1/ordini/"),
    ("KPI", "/api/v1/intelligence/kpi"),
    ("Classifica efficienza", "/api/v1/intelligence/efficiency-leaderboard"),
    ("Varianza prezzi", "/api/v1/intelligence/variance-loss"),
    ("Listino Smart", "/api/v1/smart-price-sheet/matrix?limit=5"),
)


async def main() -> None:
    validate(dict(os.environ))
    async with async_session_factory() as session:
        user = (
            await session.execute(
                select(Utente).where(Utente.email == "staging-admin@example.com")
            )
        ).scalar_one_or_none()
        if user is None or not user.attivo or user.ruolo != RuoloUtente.admin:
            raise SystemExit("STOP: expected V2 staging test admin not found")

        token = create_access_token(
            user_id=user.id,
            ruolo=user.ruolo.value,
            location_id=user.location_id,
            tenant_id=user.tenant_id or 1,
            expires_delta=timedelta(minutes=3),
        )

    failures = []
    timeout = httpx.Timeout(12.0)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        health = await client.get("/api/v1/health")
        if health.status_code != 200 or health.json().get("environment") != "staging":
            raise SystemExit("STOP: backend health does not identify staging")

        for name, path in GET_PROBES:
            started = time.monotonic()
            try:
                res = await client.get(path)
                elapsed = time.monotonic() - started
                ok = res.status_code == 200
                print(f"{'PASS' if ok else 'FAIL'}: {name}: HTTP {res.status_code} ({elapsed:.2f}s)")
                if not ok:
                    failures.append(name)
            except httpx.RequestError as exc:
                elapsed = time.monotonic() - started
                # Never print URLs, Authorization headers or response bodies.
                print(f"FAIL: {name}: {type(exc).__name__} ({elapsed:.2f}s)")
                failures.append(name)

        god = await client.get("/api/v1/god/overview")
        if god.status_code not in (401, 503):
            print(f"FAIL: SuperAdmin denied without special token: HTTP {god.status_code}")
            failures.append("SuperAdmin isolation")
        else:
            print(f"PASS: SuperAdmin denied without special token: HTTP {god.status_code}")

        # Validate that unauthenticated users cannot access private business data.
        anon = await client.get("/api/v1/categories/matrix", headers={"Authorization": ""})
        if anon.status_code < 400:
            print("FAIL: anonymous API access unexpectedly allowed")
            failures.append("anonymous access")
        else:
            print(f"PASS: anonymous API denied: HTTP {anon.status_code}")

    if failures:
        raise SystemExit(f"FAIL: {len(failures)} staging-only smoke checks require review")
    print(f"PASS: all {len(GET_PROBES)} read-only V2 API probes passed")


if __name__ == "__main__":
    asyncio.run(main())
