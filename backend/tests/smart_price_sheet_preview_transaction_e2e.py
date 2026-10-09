"""Isolated PostgreSQL transaction check for Smart Price Sheet P0.

Uses *only* disposable test tables and synthetic payloads. This is NOT the full
API/listino end-to-end suite; it validates preview ownership, payload integrity,
status handling and idempotent commit at the service level.
"""
import asyncio
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.purchase_policy import SmartPriceSheetPreview
from app.services.smart_price_sheet import commit_price_preview


def digest(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def run() -> None:
    url = os.environ["DATABASE_URL"]
    if "p0_disposable" not in url:
        raise RuntimeError("Refusing to run outside the designated disposable P0 database")
    engine = create_async_engine(url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE IF NOT EXISTS utenti (id integer PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE IF NOT EXISTS location (id integer PRIMARY KEY)"))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS smart_price_sheet_previews (
                    id uuid PRIMARY KEY,
                    payload_hash varchar(64) NOT NULL,
                    preview_payload jsonb NOT NULL,
                    commit_result jsonb,
                    status varchar(20) NOT NULL
                        CHECK (status IN ('ready', 'committed', 'expired')),
                    location_id integer REFERENCES location(id),
                    created_by integer NOT NULL REFERENCES utenti(id),
                    created_at timestamptz NOT NULL,
                    expires_at timestamptz NOT NULL,
                    committed_at timestamptz
                )
            """))
            await conn.execute(text("INSERT INTO utenti(id) VALUES (1),(2) ON CONFLICT DO NOTHING"))

        payload = {
            "can_commit": True,
            "effective_date": date.today().isoformat(),
            "location_id": None,
            "changes": [],
            "order_name_changes": [],
        }

        async def stage(*, owner: int = 1, state: str = "ready",
                        expires_at=None, hash_override=None):
            now = datetime.now(timezone.utc)
            async with session_factory() as session:
                async with session.begin():
                    p = SmartPriceSheetPreview(
                        payload_hash=hash_override or digest(payload),
                        preview_payload=payload,
                        status=state,
                        created_by=owner,
                        created_at=now,
                        expires_at=expires_at or (now + timedelta(minutes=30)),
                    )
                    session.add(p)
                    await session.flush()
                    return p.id

        token = await stage()
        async with session_factory() as session:
            async with session.begin():
                try:
                    await commit_price_preview(session, token=token, actor_id=2)
                    raise AssertionError("Other user was allowed to commit")
                except HTTPException as err:
                    assert err.status_code == 403

        async with session_factory() as session:
            async with session.begin():
                preview, result = await commit_price_preview(session, token=token, actor_id=1)
                assert preview.status == "committed"
                assert result["created"] == result["updated"] == 0

        async with session_factory() as session:
            async with session.begin():
                preview2, result2 = await commit_price_preview(session, token=token, actor_id=1)
                assert preview2.status == "committed"
                assert result2 == result

        async with session_factory() as session:
            res = await session.get(SmartPriceSheetPreview, token)
            assert res.status == "committed" and res.commit_result == result

        expired_token = await stage(expires_at=datetime.now(timezone.utc) - timedelta(seconds=5))
        async with session_factory() as session:
            async with session.begin():
                try:
                    await commit_price_preview(session, token=expired_token, actor_id=1)
                    raise AssertionError("Expired preview was accepted")
                except HTTPException as err:
                    assert err.status_code == 409

        tampered_token = await stage(hash_override="0" * 64)
        async with session_factory() as session:
            async with session.begin():
                try:
                    await commit_price_preview(session, token=tampered_token, actor_id=1)
                    raise AssertionError("Tampered preview was accepted")
                except HTTPException as err:
                    assert err.status_code == 409

        print(json.dumps({"status": "PASS", "checks": [
            "owner_required", "commit_persisted", "retry_idempotent",
            "expired_rejected", "payload_integrity_rejected"
        ]}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
