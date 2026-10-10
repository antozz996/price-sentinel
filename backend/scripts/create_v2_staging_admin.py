"""Create one test-only admin account in V2, never seed default credentials.

Invocation (after staging DB is HEALTHY):
  docker exec -it price_sentinel_v2-backend-1 \
      python scripts/create_v2_staging_admin.py

No admin password is printed, logged, or stored in the Git repository.
Refuses to run with an unsafe database configuration or existing accounts.
"""
from __future__ import annotations

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.database import async_session_factory
from app.models.utenti import Utente, RuoloUtente
from app.services.auth import hash_password
from scripts.ensure_v2_staging import validate


async def main() -> None:
    import os
    validate(dict(os.environ))

    email = "staging-admin@pricesentinel.local"
    async with async_session_factory() as session:
        result = await session.execute(select(Utente.id).limit(1))
        if result.first() is not None:
            raise SystemExit("STOP: staging user table is not empty; no changes made")

        if not sys.stdin.isatty():
            raise SystemExit("STOP: an interactive terminal is required")
        password = getpass.getpass("Choose NEW V2 admin password (16-72 bytes): ")
        if not 16 <= len(password.encode("utf-8")) <= 72:
            raise SystemExit("STOP: password must be 16-72 bytes; nothing created")
        confirmation = getpass.getpass("Repeat V2 admin password: ")
        if password != confirmation:
            raise SystemExit("STOP: passwords do not match; nothing created")
        if password.lower() in {"admin2025!", "manager2025!"}:
            raise SystemExit("STOP: example password is forbidden")

        session.add(
            Utente(
                email=email,
                password_hash=hash_password(password),
                nome_completo="Staging Administrator",
                ruolo=RuoloUtente.admin,
                ruolo_dettagliato="admin",
                settore_abilitato="all",
                location_id=None,
                attivo=True,
                tenant_id=1,
            )
        )
        await session.commit()
    print(f"PASS: V2 staging admin created: {email}")
    print("Never reuse this test password for production.")


if __name__ == "__main__":
    asyncio.run(main())
