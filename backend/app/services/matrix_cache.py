"""Shared cache of the Smart Price Sheet matrix (GET /smart-price-sheet/matrix).

Computing a 500-row page costs ~1.3 s of CPU; the order builder asks for the whole
catalog (5 pages) at every load. The finished JSON is stored in an UNLOGGED table
shared by all uvicorn workers and reused while the data it was built from is
unchanged.

Correctness rests on the fingerprint: count(*) and sum(xmin) of every table the
matrix reads (SOURCE_TABLES). Any INSERT, UPDATE or DELETE on one of them changes
it, so a stored page is served only if nothing it depends on has been written
since. The cache key also holds today's date and the price day, so date-dependent
values never cross midnight. If a computation reads a table outside
SOURCE_TABLES (new code), the result is not stored and a warning is logged:
the cache can only be bypassed, never stale.

The automation leader worker also re-computes the pages used in the last hours
as soon as the fingerprint changes (warm_loop), so the first visit after an
invoice import or a price change is fast too.

Other heavy read-only views built on the same tables (dashboard waste,
consumption report, product list) use the same cache through view() and
cached_response(): params carry their "kind" (entries without it are matrix
pages) and warm_loop finds their compute in COMPUTERS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date
from types import SimpleNamespace
from typing import Awaitable, Callable

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy import event, text

from app.database import Base, async_session_factory, engine

logger = logging.getLogger("price_sentinel.matrix_cache")

SOURCE_TABLES = (
    "fatture",
    "fornitori",
    "listino_master",
    "location",
    "product_purchase_policies",
    "product_supplier_assessments",
    "products",
    "righe_escluse_statistiche",
    "righe_fattura",
    "skus_esclusi",
    "supplier_category_capabilities",
    "supplier_price_changes",
    "supplier_product_aliases",
    "supplier_subcategory_capabilities",
    "xml_raw",
)

CACHE_DDL = (
    "CREATE UNLOGGED TABLE IF NOT EXISTS smart_matrix_cache ("
    " cache_key TEXT PRIMARY KEY,"
    " params JSONB NOT NULL,"
    " fingerprint TEXT NOT NULL,"
    " body BYTEA NOT NULL,"
    " computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
    " last_used_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)

WARM_INTERVAL_SECONDS = 20
WARM_RECENT = "3 hours"
WARM_MAX_ENTRIES = 40
DROP_UNUSED_AFTER = "2 days"

_FINGERPRINT_SQL = text(" UNION ALL ".join(
    f"SELECT '{name}' AS t, count(*) AS n, coalesce(sum(xmin::text::bigint), 0) AS x FROM {name}"
    for name in SOURCE_TABLES
))
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)")
_TOUCHED = "matrix_cache_touched"
_locks: dict[str, asyncio.Lock] = {}

Compute = Callable[..., Awaitable[dict]]
ComputeFactory = Callable[[object], Compute]
# kind -> factory(user) -> compute(db, params); filled by view() at import time.
COMPUTERS: dict[str, ComputeFactory] = {}


def view(kind: str):
    """Register a cached view: decorates factory(user) -> compute(db, params)."""
    def register(factory: ComputeFactory) -> ComputeFactory:
        COMPUTERS[kind] = factory
        return factory
    return register


def view_params(kind: str, user, **extra) -> dict:
    """Cache params of a view: kind, tenant, today's date and the request filters."""
    from app.services.tenant_scope import user_tenant_id

    return {
        "kind": kind, "tenant_id": user_tenant_id(user), "today": date.today().isoformat(),
        **{name: value.isoformat() if isinstance(value, date) else value for name, value in extra.items()},
    }


async def cached_response(db, user, kind: str, **extra) -> Response:
    """JSON response of a registered view, from the cache while the data is unchanged."""
    params = view_params(kind, user, **extra)
    body = await get_or_compute(db, params, COMPUTERS[kind](user))
    return Response(content=body, media_type="application/json")


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _record_tables(conn, cursor, statement, parameters, context, executemany):
    touched = conn.info.get(_TOUCHED)
    if touched is not None:
        touched.update(_TABLE_RE.findall(statement))


async def fingerprint(db) -> str:
    rows = (await db.execute(_FINGERPRINT_SQL)).all()
    return hashlib.sha256(repr(sorted(tuple(r) for r in rows)).encode()).hexdigest()


def cache_key(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def make_params(*, tenant_id: int, search, category, subcategory, location_id, limit, offset,
                sort, periodo, price_on: date, today: date) -> dict:
    return {
        "tenant_id": tenant_id, "search": search, "category": category, "subcategory": subcategory,
        "location_id": location_id, "limit": limit, "offset": offset, "sort": sort,
        "periodo": periodo, "price_on": price_on.isoformat(), "today": today.isoformat(),
    }


async def _compute_body(db, compute: Compute, params: dict) -> tuple[bytes, bool]:
    """Run the matrix and serialize it as FastAPI would. Returns (body, cacheable)."""
    sync_conn = (await db.connection()).sync_connection
    touched: set[str] = set()
    sync_conn.info[_TOUCHED] = touched
    try:
        result = await compute(db, params)
    finally:
        sync_conn.info.pop(_TOUCHED, None)
    unexpected = (touched & set(Base.metadata.tables)) - set(SOURCE_TABLES)
    if unexpected:
        logger.warning("matrix_cache_bypassed unexpected_tables=%s", sorted(unexpected))
    return JSONResponse(content=jsonable_encoder(result)).body, not unexpected


async def _store(db, key: str, params: dict, fp: str, body: bytes) -> None:
    try:
        async with db.begin_nested():
            await db.execute(text(
                "INSERT INTO smart_matrix_cache (cache_key, params, fingerprint, body) "
                "VALUES (:k, CAST(:p AS JSONB), :f, :b) "
                "ON CONFLICT (cache_key) DO UPDATE SET params = EXCLUDED.params, "
                "fingerprint = EXCLUDED.fingerprint, body = EXCLUDED.body, "
                "computed_at = now(), last_used_at = now()"
            ), {"k": key, "p": json.dumps(params), "f": fp, "b": body})
    except Exception:
        logger.exception("matrix_cache_store_failed")


async def _lookup(db, key: str, fp: str) -> bytes | None:
    try:
        async with db.begin_nested():
            row = (await db.execute(text(
                "SELECT fingerprint, body FROM smart_matrix_cache WHERE cache_key = :k"
            ), {"k": key})).first()
            if row is None or row.fingerprint != fp:
                return None
            await db.execute(text(
                "UPDATE smart_matrix_cache SET last_used_at = now() "
                "WHERE cache_key = :k AND last_used_at < now() - interval '1 minute'"
            ), {"k": key})
            return bytes(row.body)
    except Exception:
        logger.exception("matrix_cache_lookup_failed")
        return None


async def get_or_compute(db, params: dict, compute: Compute) -> bytes:
    """JSON body of the matrix page for params: from the cache if still valid, else computed and stored."""
    key = cache_key(params)
    fp = await fingerprint(db)
    body = await _lookup(db, key, fp)
    if body is not None:
        return body
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:  # same page requested twice at once in this worker: compute it once
        fp = await fingerprint(db)
        body = await _lookup(db, key, fp)
        if body is not None:
            return body
        body, cacheable = await _compute_body(db, compute, params)
        if cacheable:
            await _store(db, key, params, fp, body)
        return body


async def ensure_table(conn) -> None:
    await conn.execute(text(CACHE_DDL))


async def warm_once(computers: dict[str, ComputeFactory] = COMPUTERS) -> int:
    """Re-compute the recently used pages whose fingerprint is outdated. Returns how many."""
    async with async_session_factory() as db:
        await db.execute(text(
            f"DELETE FROM smart_matrix_cache WHERE last_used_at < now() - interval '{DROP_UNUSED_AFTER}'"
        ))
        await db.commit()
        today = date.today().isoformat()
        fp = await fingerprint(db)
        stale = (await db.execute(text(
            "SELECT cache_key, params FROM smart_matrix_cache "
            f"WHERE fingerprint <> :f AND last_used_at > now() - interval '{WARM_RECENT}' "
            "ORDER BY last_used_at DESC LIMIT :n"
        ), {"f": fp, "n": WARM_MAX_ENTRIES})).all()
        await db.commit()
    done = 0
    for key, params in stale:
        if params.get("today") != today:
            continue  # yesterday's key: today's pages get new keys when first opened
        factory = computers.get(params.get("kind", "matrix"))
        if factory is None:
            continue
        async with async_session_factory() as db:
            fp = await fingerprint(db)
            user = SimpleNamespace(tenant_id=params["tenant_id"], ruolo="admin", location_id=None)
            body, cacheable = await _compute_body(db, factory(user), params)
            if cacheable:
                await _store(db, key, params, fp, body)
            await db.commit()
        done += 1
        await asyncio.sleep(0)  # let pending requests of this worker run between pages
    return done


async def warm_loop() -> None:
    while True:
        await asyncio.sleep(WARM_INTERVAL_SECONDS)
        try:
            done = await warm_once()
            if done:
                logger.info("matrix_cache_warmed pages=%s", done)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("matrix_cache_warm_failed")
