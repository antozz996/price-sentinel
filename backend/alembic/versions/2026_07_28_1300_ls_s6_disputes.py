"""add auditable dispute and credit-note workflow

Revision ID: ls_s6_disputes
Revises: ls_s5_supplier_equivalence
Create Date: 2026-07-28 13:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ls_s6_disputes"
down_revision: Union[str, None] = "ls_s5_supplier_equivalence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispute_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_code", sa.String(length=40), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("liquidstock_venue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("requested_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("recognized_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("recovered_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("unrecovered_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("manual_close_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('draft','ready_to_send','sent','supplier_replied',"
            "'credit_note_expected','partially_recovered','recovered',"
            "'rejected','closed','cancelled')",
            name="ck_dispute_cases_status",
        ),
        sa.CheckConstraint(
            "requested_amount >= 0 and recognized_amount >= 0 "
            "and recovered_amount >= 0 and unrecovered_amount >= 0",
            name="ck_dispute_cases_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "recognized_amount <= requested_amount "
            "and recovered_amount <= recognized_amount "
            "and unrecovered_amount = requested_amount - recovered_amount",
            name="ck_dispute_cases_amount_consistency",
        ),
        sa.CheckConstraint(
            "(status not in ('closed','cancelled')) "
            "or length(btrim(coalesce(manual_close_reason,''))) >= 8",
            name="ck_dispute_cases_terminal_reason",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["utenti.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["purchase_order_reconciliations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_code", name="uq_dispute_cases_code"),
    )
    op.create_index("ix_dispute_cases_location_status", "dispute_cases", ["location_id", "status"])
    op.create_index("ix_dispute_cases_supplier_status", "dispute_cases", ["supplier_id", "status"])
    op.create_index("ix_dispute_cases_due_date", "dispute_cases", ["due_date"])
    op.create_index("ix_dispute_cases_venue", "dispute_cases", ["liquidstock_venue_id"])

    op.create_table(
        "dispute_case_anomalies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_anomaly_id", sa.BigInteger(), nullable=True),
        sa.Column("legacy_anomaly_id", sa.Integer(), nullable=True),
        sa.Column("claimed_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("recognized_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("recovered_amount", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("reason_snapshot", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(reconciliation_anomaly_id is not null)::integer "
            "+ (legacy_anomaly_id is not null)::integer = 1",
            name="ck_dispute_case_anomalies_one_source",
        ),
        sa.CheckConstraint(
            "claimed_amount > 0 and recognized_amount >= 0 "
            "and recovered_amount >= 0 and recognized_amount <= claimed_amount "
            "and recovered_amount <= recognized_amount",
            name="ck_dispute_case_anomalies_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_anomaly_id"], ["anomalie.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_anomaly_id"],
            ["purchase_order_reconciliation_anomalies.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reconciliation_anomaly_id",
            name="uq_dispute_case_anomalies_reconciliation",
        ),
        sa.UniqueConstraint(
            "legacy_anomaly_id", name="uq_dispute_case_anomalies_legacy"
        ),
    )
    op.create_index(
        "ix_dispute_case_anomalies_case",
        "dispute_case_anomalies",
        ["dispute_case_id"],
    )

    op.create_table(
        "dispute_communications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="prepared", nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body_snapshot", sa.Text(), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_manual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel in ('whatsapp','email','pdf','copy')",
            name="ck_dispute_communications_channel",
        ),
        sa.CheckConstraint(
            "status in ('prepared','copied','opened','sent_manual','confirmed',"
            "'response_received')",
            name="ck_dispute_communications_status",
        ),
        sa.CheckConstraint(
            "message_hash ~ '^[0-9a-f]{64}$'",
            name="ck_dispute_communications_hash",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dispute_communications_case",
        "dispute_communications",
        ["dispute_case_id", "created_at"],
    )

    op.create_table(
        "dispute_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0 and size_bytes <= 10485760",
            name="ck_dispute_attachments_size",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dispute_attachments_sha256",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dispute_attachments_case",
        "dispute_attachments",
        ["dispute_case_id", "created_at"],
    )

    op.create_table(
        "dispute_supplier_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("communication_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("responder_name", sa.String(length=255), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel in ('whatsapp','email','phone','portal','other')",
            name="ck_dispute_supplier_responses_channel",
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["dispute_attachments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["communication_id"], ["dispute_communications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["recorded_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dispute_supplier_responses_case",
        "dispute_supplier_responses",
        ["dispute_case_id", "received_at"],
    )

    op.create_table(
        "dispute_credit_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("fattura_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="received", nullable=False),
        sa.Column("document_number", sa.String(length=100), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source in ('manual','imported')",
            name="ck_dispute_credit_notes_source",
        ),
        sa.CheckConstraint(
            "status in ('received','verified','partially_allocated','allocated','rejected')",
            name="ck_dispute_credit_notes_status",
        ),
        sa.CheckConstraint(
            "total_amount > 0", name="ck_dispute_credit_notes_amount"
        ),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["fattura_id"], ["fatture.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fattura_id", name="uq_dispute_credit_notes_invoice"),
        sa.UniqueConstraint(
            "location_id",
            "supplier_id",
            "document_number",
            "issue_date",
            name="uq_dispute_credit_notes_document",
        ),
    )
    op.create_index(
        "ix_dispute_credit_notes_case",
        "dispute_credit_notes",
        ["dispute_case_id", "status"],
    )

    op.create_table(
        "dispute_credit_note_allocations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("credit_note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_anomaly_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name="ck_dispute_credit_note_allocations_amount"
        ),
        sa.ForeignKeyConstraint(
            ["case_anomaly_id"], ["dispute_case_anomalies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["credit_note_id"], ["dispute_credit_notes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "credit_note_id",
            "case_anomaly_id",
            name="uq_dispute_credit_note_allocations_item",
        ),
    )

    op.create_table(
        "dispute_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dispute_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["utenti.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["dispute_case_id"], ["dispute_cases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dispute_audit_events_case",
        "dispute_audit_events",
        ["dispute_case_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("dispute_audit_events")
    op.drop_table("dispute_credit_note_allocations")
    op.drop_table("dispute_credit_notes")
    op.drop_table("dispute_supplier_responses")
    op.drop_table("dispute_attachments")
    op.drop_table("dispute_communications")
    op.drop_table("dispute_case_anomalies")
    op.drop_table("dispute_cases")
