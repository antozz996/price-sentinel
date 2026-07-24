"""Strict v1 schemas for events produced by LiquidStock."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiquidStockOrderRow(StrictModel):
    supplier_order_item_id: UUID
    product_id: UUID | None = None
    price_sentinel_product_id: str | None = None
    product_name_snapshot: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=100)
    package_note: str | None = None
    supplier_note: str | None = None


class LiquidStockReceiptItem(StrictModel):
    supplier_order_item_id: UUID
    ordered_quantity: Decimal = Field(gt=0)
    received_quantity: Decimal = Field(ge=0)
    missing_quantity: Decimal = Field(ge=0)
    line_status: str = Field(
        pattern="^(not_delivered|partial|received|over_received)$"
    )
    note: str | None = None


class LiquidStockReceipt(StrictModel):
    id: UUID
    status: str = Field(pattern="^(partial|complete)$")
    items: list[LiquidStockReceiptItem] = Field(min_length=1)


class LiquidStockEventPayload(StrictModel):
    integration_version: str
    event_type: str
    liquidstock_order_id: UUID
    liquidstock_supplier_order_id: UUID
    venue_id: UUID
    venue_name_snapshot: str | None = None
    supplier_id: UUID
    price_sentinel_supplier_id: str | None = None
    supplier_name_snapshot: str = Field(min_length=1, max_length=255)
    sent_at: datetime | None = None
    requested_delivery_date: date | None = None
    order_version: int = Field(gt=0)
    rows: list[LiquidStockOrderRow] = Field(min_length=1)
    received_at: datetime | None = None
    receipt: LiquidStockReceipt | None = None
    cancelled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_event_shape(self):
        allowed = {
            "supplier_order_confirmed",
            "supplier_order_received",
            "supplier_order_cancelled",
        }
        if self.integration_version != "1.0":
            raise ValueError("unsupported_integration_version")
        if self.event_type not in allowed:
            raise ValueError("unsupported_event_type")
        if self.event_type == "supplier_order_confirmed":
            if (
                self.sent_at is None
                or self.receipt is not None
                or self.cancelled_at is not None
            ):
                raise ValueError("invalid_confirmed_payload")
        elif self.event_type == "supplier_order_received":
            if (
                self.sent_at is None
                or self.receipt is None
                or self.received_at is None
            ):
                raise ValueError("invalid_received_payload")
        elif self.cancelled_at is None or self.receipt is not None:
            raise ValueError("invalid_cancelled_payload")

        row_ids = [row.supplier_order_item_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("duplicate_order_row")
        if self.receipt:
            receipt_ids = [item.supplier_order_item_id for item in self.receipt.items]
            if len(receipt_ids) != len(set(receipt_ids)) or set(receipt_ids) != set(
                row_ids
            ):
                raise ValueError("receipt_rows_do_not_match_order")
            complete = True
            for item in self.receipt.items:
                expected_missing = max(
                    item.ordered_quantity - item.received_quantity,
                    Decimal("0"),
                )
                expected_status = (
                    "not_delivered"
                    if item.received_quantity == 0
                    else "over_received"
                    if item.received_quantity > item.ordered_quantity
                    else "received"
                    if item.received_quantity == item.ordered_quantity
                    else "partial"
                )
                if (
                    item.missing_quantity != expected_missing
                    or item.line_status != expected_status
                ):
                    raise ValueError("invalid_receipt_line_totals")
                complete = complete and (
                    item.received_quantity >= item.ordered_quantity
                )
            if (self.receipt.status == "complete") != complete:
                raise ValueError("invalid_receipt_status")
        return self


class IntegrationEventResponse(StrictModel):
    accepted: bool
    event_id: UUID
    duplicate: bool


class CatalogSearchRequest(StrictModel):
    query: str | None = Field(default=None, max_length=120)
    id: int | None = Field(default=None, gt=0)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def require_filter(self):
        if self.id is None and not (self.query or "").strip():
            raise ValueError("catalog_filter_required")
        return self


class SupplierCatalogItem(StrictModel):
    id: int
    name: str
    vat_number: str
    is_active: bool


class ProductCatalogItem(StrictModel):
    id: int
    name: str
    sku: str | None
    category: str | None
    is_active: bool
