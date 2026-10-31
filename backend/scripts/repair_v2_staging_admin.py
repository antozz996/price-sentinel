"""Repair ONLY a locally bootstrapped Price Sentinel V2 staging admin.

The initial bootstrap used a .local email, which fails FastAPI/Pydantic
EmailStr request validation. This fixes the email and rotates the test
password interactively because the original password was disclosed.

Invocation, from the Hetzner VPS (V2 only):
  docker cp /opt/price-sentinel-v2/backend/scripts/repair_v2_staging_admin.py \
    price_sentinel_v2-backend-1:/app/scripts/repair_v2_staging_admin.py
  docker exec -it price_sentinel_v2-backend-1 python -m scripts.repair_v2_staging_admin

Do NOT run against production. Does NOT print passwords.
"""
from __future__ import annotations

import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models.utenti import RuoloUtente, Utente
from app.schemas.utenti import UtenteLogin
from app.services.auth import hash_password
from scripts.ensure_v2_staging import validate

OLD_EMAIL = "staging-admin@pricesentinel.local"
NEW_EMAIL = "staging-admin@example.com"


async def main() -> None:
    validate(dict(os.environ))
    # Ensure FastAPI's own login validator accepts the replacement email.
    UtenteLogin(email=NEW_EMAIL, password="schema-check-only")

    async with async_session_factory() as session:
        result = await session.execute(select(func.count()).select_from(Utente))
        if result.scalar_one() != 1:
            raise SystemExit("STOP: expected exactly one staging account; no changes")

        result = await session.execute(select(Utente))
        admin = result.scalar_one()
        if (
            admin.email not in {OLD_EMAIL, NEW_EMAIL}
            or admin.ruolo != RuoloUtente.admin
            or not admin.attivo
            or admin.location_id is not None
        ):
            raise SystemExit("STOP: unexpected staging admin state; no changes")

        if not sys.stdin.isatty():
            raise SystemExit("STOP: interactive terminal required")
        new_password = getpass.getpass("New DIFFERENT V2 password (16-72 bytes): ")
        if not 16 <= len(new_password.encode("utf-8")) <= 72:
            raise SystemExit("STOP: new password length must be 16-72 bytes")
        confirmation = getpass.getpass("Confirm new V2 password: ")
        if new_password != confirmation:
            raise SystemExit("STOP: passwords do not match")
        if new_password.lower() in {"admin2025!", "manager2025!"}:
            raise SystemExit("STOP: example password forbidden")

        # One staging-only transaction changes BOTH the address and password.
        admin.email = NEW_EMAIL
        admin.password_hash = hash_password(new_password)
        await session.commit()

    print("PASS: V2 staging administrator email corrected and password rotated")
    print("Login email:", NEW_EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
