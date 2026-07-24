"""Transactional projection of validated LiquidStock events."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fornitori import Fornitore
from app.models.liquidstock_integration import (
    LiquidStockIntegrationEvent,
    LiquidStockSupplierOrder,
    LiquidStockSupplierOrderItem,
)
from app.models.products import Product
from app.schemas.liquidstock_integration import LiquidStockEventPayload


class ProjectionError(Exception):
    def __init__(self, code: str, http_status: int = 409):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


async def _resolve_supplier_id(
    db: AsyncSession, external_id: str | None
) -> int | None:
    if external_id is None:
        return None
    try:
        supplier_id = int(external_id)
    except ValueError:
        raise ProjectionError("invalid_supplier_mapping", 422) from None
    if supplier_id <= 0 or not await db.scalar(
        select(Fornitore.id).where(Fornitore.id == supplier_id)
    ):
        raise ProjectionError("supplier_mapping_not_found", 422)
    return supplier_id


async def _resolve_product_id(
    db: AsyncSession, external_id: str | None
) -> int | None:
    if external_id is None:
        return None
    try:
        product_id = int(external_id)
    except ValueError:
        raise ProjectionError("invalid_product_mapping", 422) from None
    if product_id <= 0 or not await db.scalar(
        select(Product.id).where(Product.id == product_id)
    ):
        raise ProjectionError("product_mapping_not_found", 422)
    return product_id


async def _validated_mappings(
    db: AsyncSession, payload: LiquidStockEventPayload
) -> tuple[int | None, dict]:
    supplier_id = await _resolve_supplier_id(
        db, payload.price_sentinel_supplier_id
    )
    product_ids = {}
    for row in payload.rows:
        product_ids[row.supplier_order_item_id] = await _resolve_product_id(
            db, row.price_sentinel_product_id
        )
    return supplier_id, product_ids


async def _create_order(
    db: AsyncSession,
    event: LiquidStockIntegrationEvent,
    payload: LiquidStockEventPayload,
    status: str,
    supplier_id: int | None,
    product_ids: dict,
) -> LiquidStockSupplierOrder:
    now = datetime.now(timezone.utc)
    order = LiquidStockSupplierOrder(
        liquidstock_order_id=payload.liquidstock_order_id,
        liquidstock_supplier_order_id=payload.liquidstock_supplier_order_id,
        liquidstock_venue_id=payload.venue_id,
        venue_name_snapshot=payload.venue_name_snapshot,
        liquidstock_supplier_id=payload.supplier_id,
        supplier_id=supplier_id,
        supplier_name_snapshot=payload.supplier_name_snapshot,
        order_version=payload.order_version,
        status=status,
        sent_at=payload.sent_at,
        requested_delivery_date=payload.requested_delivery_date,
        received_at=payload.received_at if status == "received" else None,
        cancelled_at=payload.cancelled_at if status == "cancelled" else None,
        last_event_id=event.external_event_id,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    await db.flush()
    for row in payload.rows:
        db.add(
            LiquidStockSupplierOrderItem(
                supplier_order_id=order.id,
                liquidstock_supplier_order_item_id=row.supplier_order_item_id,
                liquidstock_product_id=row.product_id,
                product_id=product_ids[row.supplier_order_item_id],
                product_name_snapshot=row.product_name_snapshot,
                quantity=row.quantity,
                unit=row.unit,
                package_note=row.package_note,
                supplier_note=row.supplier_note,
                ordered_quantity=row.quantity,
                received_quantity=None,
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()
    return order


def _assert_identity(
    order: LiquidStockSupplierOrder, payload: LiquidStockEventPayload
) -> None:
    if (
        order.liquidstock_order_id != payload.liquidstock_order_id
        or order.liquidstock_venue_id != payload.venue_id
        or order.liquidstock_supplier_id != payload.supplier_id
        or order.order_version != payload.order_version
    ):
        raise ProjectionError("supplier_order_identity_conflict")


async def apply_liquidstock_event(
    db: AsyncSession,
    event: LiquidStockIntegrationEvent,
    payload: LiquidStockEventPayload,
) -> None:
    supplier_id, product_ids = await _validated_mappings(db, payload)
    order = await db.scalar(
        select(LiquidStockSupplierOrder)
        .where(
            LiquidStockSupplierOrder.liquidstock_supplier_order_id
            == payload.liquidstock_supplier_order_id
        )
        .with_for_update()
    )

    if payload.event_type == "supplier_order_confirmed":
        if order is not None:
            _assert_identity(order, payload)
            raise ProjectionError("supplier_order_already_confirmed")
        await _create_order(
            db, event, payload, "confirmed", supplier_id, product_ids
        )
        return

    if payload.event_type == "supplier_order_cancelled":
        if order is None:
            await _create_order(
                db, event, payload, "cancelled", supplier_id, product_ids
            )
            return
        _assert_identity(order, payload)
        if order.status == "received":
            raise ProjectionError("received_supplier_order_is_terminal")
        if order.status == "cancelled":
            raise ProjectionError("supplier_order_already_cancelled")
        order.status = "cancelled"
        order.cancelled_at = payload.cancelled_at
        order.last_event_id = event.external_event_id
        order.updated_at = datetime.now(timezone.utc)
        return

    if order is None:
        raise ProjectionError("confirmed_event_required")
    _assert_identity(order, payload)
    if order.status == "cancelled":
        raise ProjectionError("cancelled_supplier_order_is_terminal")
    if order.status == "received":
        raise ProjectionError("received_supplier_order_is_terminal")

    if supplier_id is not None:
        if order.supplier_id is not None and order.supplier_id != supplier_id:
            raise ProjectionError("supplier_mapping_conflict", 422)
        order.supplier_id = supplier_id

    existing_items = {
        item.liquidstock_supplier_order_item_id: item
        for item in (
            await db.scalars(
                select(LiquidStockSupplierOrderItem)
                .where(LiquidStockSupplierOrderItem.supplier_order_id == order.id)
                .with_for_update()
            )
        ).all()
    }
    if set(existing_items) != {
        row.supplier_order_item_id for row in payload.rows
    }:
        raise ProjectionError("supplier_order_rows_changed")

    receipt_by_id = {
        item.supplier_order_item_id: item for item in payload.receipt.items
    }
    now = datetime.now(timezone.utc)
    for row in payload.rows:
        stored = existing_items[row.supplier_order_item_id]
        if (
            stored.liquidstock_product_id != row.product_id
            or stored.product_name_snapshot != row.product_name_snapshot
            or Decimal(stored.ordered_quantity) != row.quantity
            or stored.unit != row.unit
        ):
            raise ProjectionError("supplier_order_snapshot_changed")
        incoming_product_id = product_ids[row.supplier_order_item_id]
        if incoming_product_id is not None:
            if stored.product_id is not None and stored.product_id != incoming_product_id:
                raise ProjectionError("product_mapping_conflict", 422)
            stored.product_id = incoming_product_id
        receipt_item = receipt_by_id[row.supplier_order_item_id]
        if receipt_item.ordered_quantity != Decimal(stored.ordered_quantity):
            raise ProjectionError("receipt_ordered_quantity_mismatch", 422)
        stored.received_quantity = receipt_item.received_quantity
        stored.updated_at = now

    order.status = (
        "received" if payload.receipt.status == "complete" else "partially_received"
    )
    order.received_at = payload.received_at
    order.last_event_id = event.external_event_id
    order.updated_at = now
