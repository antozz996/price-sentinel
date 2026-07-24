"""Persistence models for the LiquidStock inbound integration."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LiquidStockIntegrationEvent(Base):
    __tablename__ = "liquidstock_integration_events"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_event_id",
            name="uq_liquidstock_integration_events_source_event",
        ),
        CheckConstraint(
            "processing_status in ('received','processed','failed')",
            name="ck_liquidstock_integration_events_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    integration_version: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="received", server_default="received"
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LiquidStockSupplierOrder(Base):
    __tablename__ = "liquidstock_supplier_orders"
    __table_args__ = (
        UniqueConstraint(
            "liquidstock_supplier_order_id",
            name="uq_liquidstock_supplier_orders_external_id",
        ),
        CheckConstraint(
            "status in ('confirmed','partially_received','received','cancelled')",
            name="ck_liquidstock_supplier_orders_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    liquidstock_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    liquidstock_supplier_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    liquidstock_venue_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    venue_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    liquidstock_supplier_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    supplier_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supplier_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    order_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    items = relationship(
        "LiquidStockSupplierOrderItem",
        back_populates="supplier_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class LiquidStockSupplierOrderItem(Base):
    __tablename__ = "liquidstock_supplier_order_items"
    __table_args__ = (
        UniqueConstraint(
            "supplier_order_id",
            "liquidstock_supplier_order_item_id",
            name="uq_liquidstock_supplier_order_items_external_id",
        ),
        CheckConstraint(
            "quantity > 0 and ordered_quantity > 0",
            name="ck_liquidstock_supplier_order_items_positive",
        ),
        CheckConstraint(
            "received_quantity is null or received_quantity >= 0",
            name="ck_liquidstock_supplier_order_items_received",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("liquidstock_supplier_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    liquidstock_supplier_order_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    liquidstock_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    product_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(100), nullable=False)
    package_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    received_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    supplier_order = relationship(
        "LiquidStockSupplierOrder", back_populates="items"
    )
