"""Fail-closed startup guard for the isolated Price Sentinel V2 staging backend.

This MUST run before Uvicorn. It checks the target DATABASE_URL without
connecting to the database or exposing secrets. Production is never an allowed
target for this staging stack.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url

EXPECTED_DATABASE = "price_sentinel_v2_staging"
EXPECTED_USER = "ps_v2_app"
EXPECTED_HOST = "db"


def validate(environment: dict[str, str]) -> None:
    if environment.get("ENVIRONMENT", "").lower() != "staging":
        raise ValueError("Staging guard: ENVIRONMENT must be staging")
    if environment.get("DEBUG", "").lower() not in {"false", "0", "off"}:
        raise ValueError("Staging guard: DEBUG must be disabled")
    if environment.get("AUTOMATION_ENABLED", "").lower() not in {"false", "0", "off"}:
        raise ValueError("Staging guard: scheduled automations must be disabled")

    raw = environment.get("DATABASE_URL", "")
    if not raw:
        raise ValueError("Staging guard: a dedicated DATABASE_URL is mandatory")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise ValueError("Staging guard: invalid DATABASE_URL") from exc
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("Staging guard: expected PostgreSQL asyncpg driver")
    if (url.host, url.database, url.username) != (
        EXPECTED_HOST, EXPECTED_DATABASE, EXPECTED_USER
    ):
        raise ValueError("Staging guard: only the isolated V2 PostgreSQL database is allowed")
    if url.port not in (None, 5432):
        raise ValueError("Staging guard: unexpected PostgreSQL port")
    if not url.password or len(url.password) < 16:
        raise ValueError("Staging guard: set a unique random database password")


def main() -> None:
    try:
        validate(dict(os.environ))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print("PASS: V2 staging database isolation and unsafe-feature checks")


if __name__ == "__main__":
    main()
