"""add smart price sheet and supplier purchase policies

Revision ID: smart_price_policy
Revises: ls_s8_onboarding
Create Date: 2026-08-06 17:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "smart_price_policy"
down_revision: Union[str, None] = "ls_s8_onboarding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_supplier_assessments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="approved", nullable=False),
        sa.Column("quality_score", sa.Integer(), server_default="3", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('approved','discouraged','blocked')",
            name="ck_product_supplier_assessments_status",
        ),
        sa.CheckConstraint(
            "quality_score between 1 and 5",
            name="ck_product_supplier_assessments_quality",
        ),
        sa.CheckConstraint(
            "status = 'approved' or coalesce(length(btrim(reason)), 0) >= 3",
            name="ck_product_supplier_assessments_reason",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_product_supplier_assessment_global",
        "product_supplier_assessments",
        ["product_id", "supplier_id"],
        unique=True,
        postgresql_where=sa.text("location_id is null"),
    )
    op.create_index(
        "uq_product_supplier_assessment_location",
        "product_supplier_assessments",
        ["product_id", "supplier_id", "location_id"],
        unique=True,
        postgresql_where=sa.text("location_id is not null"),
    )
    op.create_index(
        "ix_product_supplier_assessments_lookup",
        "product_supplier_assessments",
        ["product_id", "location_id", "status"],
    )

    op.create_table(
        "product_supplier_assessment_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("assessment_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action in ('created','updated')",
            name="ck_product_supplier_assessment_audits_action",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["product_supplier_assessments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_supplier_assessment_audits_assessment_id",
        "product_supplier_assessment_audits",
        ["assessment_id"],
    )

    op.create_table(
        "product_purchase_policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column(
            "selection_mode", sa.String(30), server_default="best_eligible_price", nullable=False
        ),
        sa.Column("preferred_supplier_id", sa.Integer(), nullable=True),
        sa.Column("minimum_quality", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "max_price_premium_percent", sa.Numeric(8, 4), server_default="0", nullable=False
        ),
        sa.Column(
            "max_price_premium_absolute", sa.Numeric(12, 4), server_default="0", nullable=False
        ),
        sa.Column("allow_spot", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "selection_mode in ('manual','best_eligible_price','absolute_lowest')",
            name="ck_product_purchase_policies_mode",
        ),
        sa.CheckConstraint(
            "minimum_quality between 1 and 5",
            name="ck_product_purchase_policies_quality",
        ),
        sa.CheckConstraint(
            "max_price_premium_percent >= 0 and max_price_premium_absolute >= 0",
            name="ck_product_purchase_policies_premium",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["preferred_supplier_id"], ["fornitori.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_product_purchase_policy_global",
        "product_purchase_policies",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("location_id is null"),
    )
    op.create_index(
        "uq_product_purchase_policy_location",
        "product_purchase_policies",
        ["product_id", "location_id"],
        unique=True,
        postgresql_where=sa.text("location_id is not null"),
    )
    op.create_index(
        "ix_product_purchase_policies_lookup",
        "product_purchase_policies",
        ["product_id", "location_id"],
    )

    op.create_table(
        "product_purchase_policy_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action in ('created','updated')",
            name="ck_product_purchase_policy_audits_action",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["product_purchase_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_purchase_policy_audits_policy_id",
        "product_purchase_policy_audits",
        ["policy_id"],
    )

    op.create_table(
        "purchase_policy_deviations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("recommended_supplier_id", sa.Integer(), nullable=True),
        sa.Column("selected_supplier_id", sa.Integer(), nullable=False),
        sa.Column("deviation_type", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "deviation_type in ('manual_override','blocked_supplier','discouraged_supplier',"
            "'quality_below_minimum','premium_exceeded','spot_not_allowed')",
            name="ck_purchase_policy_deviations_type",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["recommended_supplier_id"], ["fornitori.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["selected_supplier_id"], ["fornitori.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["utenti.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_purchase_policy_deviations_dedupe_key"),
    )
    op.create_index(
        "ix_purchase_policy_deviations_scope",
        "purchase_policy_deviations",
        ["location_id", "product_id", "occurred_at"],
    )

    op.create_table(
        "smart_price_sheet_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("preview_payload", postgresql.JSONB(), nullable=False),
        sa.Column("commit_result", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(20), server_default="ready", nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('ready','committed','expired')",
            name="ck_smart_price_sheet_previews_status",
        ),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_smart_price_sheet_previews_expiry",
        "smart_price_sheet_previews",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("smart_price_sheet_previews")
    op.drop_table("purchase_policy_deviations")
    op.drop_table("product_purchase_policy_audits")
    op.drop_table("product_purchase_policies")
    op.drop_table("product_supplier_assessment_audits")
    op.drop_table("product_supplier_assessments")
