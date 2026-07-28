"""add order, receipt and invoice reconciliation domain

Revision ID: ls_s5_reconcile
Revises: ls_s4_inbound
Create Date: 2026-07-24 22:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "ls_s5_reconcile"
down_revision: Union[str, None] = "ls_s4_inbound"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "liquidstock_venue_mappings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("liquidstock_venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("venue_name_snapshot", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("liquidstock_venue_id", name="uq_liquidstock_venue_mappings_venue"),
        sa.UniqueConstraint("location_id", name="uq_liquidstock_venue_mappings_location"),
    )
    op.create_table(
        "purchase_order_reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("liquidstock_supplier_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("liquidstock_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("fattura_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), server_default="awaiting_invoice", nullable=False),
        sa.Column("matching_confidence", sa.Numeric(6, 5), server_default="0", nullable=False),
        sa.Column("reconciliation_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("price_tolerance_absolute", sa.Numeric(12, 4), server_default="0.01", nullable=False),
        sa.Column("price_tolerance_percent", sa.Numeric(8, 4), server_default="1.0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('pending','awaiting_invoice','matching','partially_matched','matched','anomalies_found','reviewed','closed')", name="ck_po_reconciliations_status"),
        sa.CheckConstraint("matching_confidence >= 0 and matching_confidence <= 1", name="ck_po_reconciliations_confidence"),
        sa.CheckConstraint("price_tolerance_absolute >= 0 and price_tolerance_percent >= 0", name="ck_po_reconciliations_tolerances"),
        sa.ForeignKeyConstraint(["fattura_id"], ["fatture.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("liquidstock_supplier_order_id", name="uq_po_reconciliations_supplier_order"),
        sa.UniqueConstraint("fattura_id", name="uq_po_reconciliations_invoice"),
    )
    op.create_index("ix_po_reconciliations_venue_status", "purchase_order_reconciliations", ["venue_id", "status", "updated_at"])
    op.create_index("ix_po_reconciliations_supplier", "purchase_order_reconciliations", ["supplier_id"])
    op.create_table(
        "purchase_order_reconciliation_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("liquidstock_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("riga_fattura_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("order_product_name", sa.Text(), nullable=True),
        sa.Column("invoice_product_description", sa.Text(), nullable=True),
        sa.Column("ordered_package_note", sa.Text(), nullable=True),
        sa.Column("ordered_quantity", sa.Numeric(18, 6), nullable=True),
        sa.Column("received_quantity", sa.Numeric(18, 6), nullable=True),
        sa.Column("invoiced_quantity", sa.Numeric(18, 6), nullable=True),
        sa.Column("ordered_unit", sa.String(100), nullable=True),
        sa.Column("invoiced_unit", sa.String(100), nullable=True),
        sa.Column("expected_unit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("expected_price_source", sa.String(80), nullable=True),
        sa.Column("invoiced_unit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("price_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("disputed_amount", sa.Numeric(18, 6), nullable=True),
        sa.Column("match_status", sa.String(40), nullable=False),
        sa.Column("anomaly_type", sa.String(50), nullable=True),
        sa.Column("match_method", sa.String(50), nullable=True),
        sa.Column("match_confidence", sa.Numeric(6, 5), server_default="0", nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("candidate_evidence", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("match_status in ('matched','quantity_mismatch','price_mismatch','unit_mismatch','unordered_item','missing_invoice_item','ambiguous','ignored')", name="ck_po_reconciliation_items_status"),
        sa.CheckConstraint("match_confidence >= 0 and match_confidence <= 1", name="ck_po_reconciliation_items_confidence"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reconciliation_id"], ["purchase_order_reconciliations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["riga_fattura_id"], ["righe_fattura.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reconciliation_id", "liquidstock_item_id", "riga_fattura_id", name="uq_po_reconciliation_item_pair"),
    )
    op.create_index("ix_po_reconciliation_items_reconciliation", "purchase_order_reconciliation_items", ["reconciliation_id", "match_status"])
    op.create_table(
        "purchase_order_reconciliation_anomalies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_item_id", sa.BigInteger(), nullable=True),
        sa.Column("fattura_id", sa.Integer(), nullable=True),
        sa.Column("riga_fattura_id", sa.Integer(), nullable=True),
        sa.Column("liquidstock_supplier_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("liquidstock_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anomaly_type", sa.String(50), nullable=False),
        sa.Column("disputed_amount", sa.Numeric(18, 6), nullable=True),
        sa.Column("evidence_key", sa.String(160), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("workflow_status", sa.String(30), server_default="da_verificare", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("anomaly_type in ('quantity_overbilled','quantity_underbilled','unordered_item','missing_invoice_item','price_overcharge','unit_mismatch','supplier_mismatch','duplicate_invoice_line','ambiguous_match','order_not_found')", name="ck_po_reconciliation_anomalies_type"),
        sa.CheckConstraint("workflow_status in ('da_verificare','in_parking','accettata','contestata','in_reclamo','risolta','ignorata')", name="ck_po_reconciliation_anomalies_workflow"),
        sa.ForeignKeyConstraint(["fattura_id"], ["fatture.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reconciliation_id"], ["purchase_order_reconciliations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reconciliation_item_id"], ["purchase_order_reconciliation_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["riga_fattura_id"], ["righe_fattura.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reconciliation_id", "evidence_key", name="uq_po_reconciliation_anomaly_evidence"),
    )
    op.create_index("ix_po_reconciliation_anomalies_workflow", "purchase_order_reconciliation_anomalies", ["venue_id", "workflow_status", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(sa.text("select count(*) from purchase_order_reconciliations")).scalar_one()
    if count:
        raise RuntimeError("Refusing destructive rollback: operational reconciliations exist")
    op.drop_table("purchase_order_reconciliation_anomalies")
    op.drop_table("purchase_order_reconciliation_items")
    op.drop_table("purchase_order_reconciliations")
    op.drop_table("liquidstock_venue_mappings")
