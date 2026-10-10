"""Run existing E2E modules against individually isolated, disposable CI DBs.

This runner is intentionally unusable on Hetzner or local production: it
requires GitHub-hosted Actions environment, a loopback PostgreSQL service and
the CI-only database role. All test writes go to a newly-created, dedicated DB.
No V1 or shared V2 staging addresses, credentials or datasets are used.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


CASES = {
    "preview": ("smart_price_sheet_preview_transaction_e2e.py", "ps_ci_disposable_p0_disposable", False),
    "smart_price_sheet": ("smart_price_sheet_e2e.py", "ps_ci_disposable_smart_sheet", True),
    "order_reconciliation": ("purchase_order_reconciliation_e2e.py", "ps_ci_disposable_orders", True),
    "disputes": ("disputes_credit_notes_e2e.py", "ps_ci_disposable_disputes", True),
    "supplier_equivalence": ("supplier_identity_equivalence_e2e.py", "ps_ci_disposable_suppliers", True),
}


def gate_environment() -> str:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or os.environ.get("CI") != "true"
    ):
        raise SystemExit("STOP: tests may run only on ephemeral GitHub-hosted CI runners")
    dsn = os.environ.get("CI_POSTGRES_ADMIN_DSN", "")
    try:
        u = make_url(dsn)
    except Exception as exc:
        raise SystemExit("STOP: invalid CI PostgreSQL URL") from exc
    if (
        u.drivername != "postgresql+psycopg2"
        or u.host != "127.0.0.1"
        or u.port != 5432
        or u.username != "ps_ci_runner"
        or u.database != "postgres"
        or not u.password
    ):
        raise SystemExit("STOP: CI PostgreSQL may connect only to loopback ephemeral runner")
    return dsn


async def create_tables(database_url: str) -> None:
    # Import only AFTER the test database environment is set.
    from app.database import Base, engine
    import app.models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


def execute_case(name: str, admin_dsn: str) -> bool:
    from sqlalchemy.engine import make_url
    import psycopg2

    test_file, db_name, bootstrap_schema = CASES[name]
    if not db_name.startswith("ps_ci_disposable_"):
        raise SystemExit("STOP: non-disposable database name")

    # Unique DB per suite; CI postgres runs only for this workflow job.
    # psycopg2 expects a PostgreSQL URI, not SQLAlchemy's "+psycopg2" dialect URL.
    admin_uri = make_url(admin_dsn).set(drivername="postgresql").render_as_string(hide_password=False)
    # CREATE DATABASE must not run inside a transaction: psycopg2's
    # "with connection" context starts one even with autocommit enabled.
    connection = psycopg2.connect(admin_uri)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("select 1 from pg_database where datname=%s", (db_name,))
            if cursor.fetchone():
                raise SystemExit("STOP: expected a brand-new disposable test DB")
            from psycopg2 import sql
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    finally:
        connection.close()

    original_url = make_url(admin_dsn)
    async_dsn = original_url.set(drivername="postgresql+asyncpg", database=db_name).render_as_string(hide_password=False)
    sync_dsn = original_url.set(database=db_name).render_as_string(hide_password=False)
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": async_dsn,
            "TEST_DATABASE_DSN": sync_dsn,
            "ENVIRONMENT": "ci",
            "DEBUG": "false",
            "AUTOMATION_ENABLED": "false",
            "SECRET_KEY": secrets.token_urlsafe(48),
            "ARUBA_WEBHOOK_API_KEY": secrets.token_urlsafe(32),
            "LIQUIDSTOCK_INTEGRATION_SECRET": secrets.token_urlsafe(48),
            "GOD_MODE_TOKEN": "",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
    )
    if bootstrap_schema:
        bootstrap = subprocess.run(
            [
                sys.executable,
                "-c",
                "import asyncio; from scripts.run_ci_disposable_e2e import create_tables; "
                "asyncio.run(create_tables(__import__('os').environ['DATABASE_URL']))",
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            check=False,
            timeout=120,
        )
        if bootstrap.returncode:
            print(f"FAIL: {name} — disposable schema bootstrap failed", flush=True)
            return False

    print(f"RUN: {name} against its independent CI-only disposable DB", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "tests" / test_file)],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            check=False,
            timeout=150,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: {name} — timeout after 150 seconds", flush=True)
        return False
    passed = result.returncode == 0
    print(f"{'PASS' if passed else 'FAIL'}: {name}", flush=True)
    return passed


def main() -> None:
    if sys.argv[1:] != ["--github-ephemeral-only"]:
        raise SystemExit("STOP: explicit --github-ephemeral-only required")
    dsn = gate_environment()
    print("PASS: GitHub-hosted disposable Postgres isolation guard", flush=True)
    failures: list[str] = []
    for name in CASES:
        if not execute_case(name, dsn):
            failures.append(name)
    if failures:
        raise SystemExit("FAIL: isolated E2E suites: " + ", ".join(failures))
    print(f"PASS: {len(CASES)} isolated database E2E suites completed", flush=True)


if __name__ == "__main__":
    main()
