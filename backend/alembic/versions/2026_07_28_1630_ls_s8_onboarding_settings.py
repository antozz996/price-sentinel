"""add venue reconciliation and onboarding settings

Revision ID: ls_s8_onboarding
Revises: ls_s7_automation
Create Date: 2026-07-28 16:30:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ls_s8_onboarding"
down_revision: Union[str, None] = "ls_s7_automation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "location_reconciliation_settings",
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column(
            "price_tolerance_absolute",
            sa.Numeric(12, 4),
            server_default="0.01",
            nullable=False,
        ),
        sa.Column(
            "price_tolerance_percent",
            sa.Numeric(8, 4),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "important_anomaly_threshold",
            sa.Numeric(12, 2),
            server_default="50",
            nullable=False,
        ),
        sa.Column(
            "stalled_reconciliation_days",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "missing_credit_note_days",
            sa.Integer(),
            server_default="7",
            nullable=False,
        ),
        sa.Column(
            "notifications_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "price_tolerance_absolute >= 0 "
            "and price_tolerance_percent >= 0 "
            "and important_anomaly_threshold > 0",
            name="ck_location_reconciliation_settings_amounts",
        ),
        sa.CheckConstraint(
            "stalled_reconciliation_days between 1 and 90 "
            "and missing_credit_note_days between 1 and 180",
            name="ck_location_reconciliation_settings_days",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["utenti.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["location.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["utenti.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("location_id"),
    )


def downgrade() -> None:
    op.drop_table("location_reconciliation_settings")
