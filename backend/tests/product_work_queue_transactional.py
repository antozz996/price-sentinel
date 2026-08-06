"""Transactional smoke test for the grouped product work queue.

The write path is fully rolled back; production records are not retained.
"""

import asyncio
import json

from sqlalchemy import select

from app.api.v1.product_identity import (
    WorkQueueResolutionProduct,
    WorkQueueResolutionRequest,
    get_match_work_queue,
    resolve_match_work_queue_item,
)
from app.database import async_session_factory
from app.models.fatture import RigaFattura, StatoMatching
from app.models.products import Product


async def run():
    checks = []
    async with async_session_factory() as db:
        queue = await get_match_work_queue(db=db, _admin=object())
        assert queue["summary"]["work_items"] < queue["summary"]["invoice_lines"]
        assert queue["summary"]["weak_candidates_hidden"] > 0
        checks.append("queue groups repeated invoice lines")
        checks.append("weak candidates are hidden")

        item = queue["items"][0]
        line_ids = item["invoice_line_ids"]
        await db.rollback()

        transaction = await db.begin()
        response = await resolve_match_work_queue_item(
            WorkQueueResolutionRequest(
                invoice_line_ids=line_ids,
                action="create_canonical",
                canonical_data=WorkQueueResolutionProduct(
                    canonical_name="TRANSACTIONAL TEST PRODUCT",
                    category="test",
                    comparison_unit="piece",
                ),
            ),
            db=db,
            _admin=object(),
        )
        assert response["resolved_lines"] == len(line_ids)
        assert response["created_product"] is True
        assert all(
            state == StatoMatching.matched
            for state in (await db.scalars(
                select(RigaFattura.stato_matching).where(RigaFattura.id.in_(line_ids))
            )).all()
        )
        created_product_id = response["product_id"]
        checks.append("one action resolves every identical occurrence")
        checks.append("quick creation and alias path completes")
        await transaction.rollback()

    async with async_session_factory() as verification_db:
        assert await verification_db.get(Product, created_product_id) is None
        assert all(
            state == StatoMatching.in_parking
            for state in (await verification_db.scalars(
                select(RigaFattura.stato_matching).where(RigaFattura.id.in_(line_ids))
            )).all()
        )
        checks.append("transaction rollback leaves production data unchanged")

    print(json.dumps({"status": "PASS", "tests": len(checks), "results": checks}, indent=2))


asyncio.run(run())
