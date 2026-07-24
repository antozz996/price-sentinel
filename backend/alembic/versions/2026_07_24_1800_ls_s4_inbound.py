"""add LiquidStock signed inbound integration

Revision ID: ls_s4_inbound
Revises: 26cfd21178be
Create Date: 2026-07-24 18:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ls_s4_inbound"
down_revision: Union[str, None] = "26cfd21178be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liquidstock_integration_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "external_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("integration_version", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default="received",
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "processing_status in ('received','processed','failed')",
            name="ck_liquidstock_integration_events_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "external_event_id",
            name="uq_liquidstock_integration_events_source_event",
        ),
    )
    op.create_index(
        "ix_liquidstock_integration_events_status_received",
        "liquidstock_integration_events",
        ["processing_status", "received_at"],
        unique=False,
    )

    op.create_table(
        "liquidstock_supplier_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "liquidstock_order_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "liquidstock_supplier_order_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "liquidstock_venue_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("venue_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column(
            "liquidstock_supplier_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('confirmed','partially_received','received','cancelled')",
            name="ck_liquidstock_supplier_orders_status",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "liquidstock_supplier_order_id",
            name="uq_liquidstock_supplier_orders_external_id",
        ),
    )
    op.create_index(
        "ix_liquidstock_supplier_orders_order",
        "liquidstock_supplier_orders",
        ["liquidstock_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_liquidstock_supplier_orders_venue",
        "liquidstock_supplier_orders",
        ["liquidstock_venue_id"],
        unique=False,
    )
    op.create_index(
        "ix_liquidstock_supplier_orders_supplier",
        "liquidstock_supplier_orders",
        ["supplier_id"],
        unique=False,
    )

    op.create_table(
        "liquidstock_supplier_order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("supplier_order_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "liquidstock_supplier_order_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "liquidstock_product_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=False),
        sa.Column("package_note", sa.Text(), nullable=True),
        sa.Column("supplier_note", sa.Text(), nullable=True),
        sa.Column(
            "ordered_quantity", sa.Numeric(precision=18, scale=6), nullable=False
        ),
        sa.Column(
            "received_quantity", sa.Numeric(precision=18, scale=6), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0 and ordered_quantity > 0",
            name="ck_liquidstock_supplier_order_items_positive",
        ),
        sa.CheckConstraint(
            "received_quantity is null or received_quantity >= 0",
            name="ck_liquidstock_supplier_order_items_received",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_order_id"],
            ["liquidstock_supplier_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_order_id",
            "liquidstock_supplier_order_item_id",
            name="uq_liquidstock_supplier_order_items_external_id",
        ),
    )
    op.create_index(
        "ix_liquidstock_supplier_order_items_order",
        "liquidstock_supplier_order_items",
        ["supplier_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_liquidstock_supplier_order_items_product",
        "liquidstock_supplier_order_items",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    event_count = connection.execute(
        sa.text("select count(*) from liquidstock_integration_events")
    ).scalar_one()
    order_count = connection.execute(
        sa.text("select count(*) from liquidstock_supplier_orders")
    ).scalar_one()
    if event_count or order_count:
        raise RuntimeError(
            "Refusing destructive rollback: LiquidStock integration data exists"
        )
    op.drop_table("liquidstock_supplier_order_items")
    op.drop_table("liquidstock_supplier_orders")
    op.drop_table("liquidstock_integration_events")
