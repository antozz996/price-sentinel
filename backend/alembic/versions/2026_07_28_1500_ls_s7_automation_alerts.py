"""add safe idempotent automation alerts

Revision ID: ls_s7_automation
Revises: ls_s6_disputes
Create Date: 2026-07-28 15:00:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ls_s7_automation"
down_revision: Union[str, None] = "ls_s6_disputes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("alert_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity in ('info','warning','critical')",
            name="ck_automation_alerts_severity",
        ),
        sa.CheckConstraint(
            "status in ('open','acknowledged','resolved')",
            name="ck_automation_alerts_status",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"], ["utenti.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["location.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dedupe_key", name="uq_automation_alerts_dedupe_key"
        ),
    )
    op.create_index(
        "ix_automation_alerts_status_severity",
        "automation_alerts",
        ["status", "severity", "last_detected_at"],
    )
    op.create_index(
        "ix_automation_alerts_location_status",
        "automation_alerts",
        ["location_id", "status"],
    )
    op.create_index(
        "ix_automation_alerts_type",
        "automation_alerts",
        ["alert_type"],
    )

    op.create_table(
        "automation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerts_detected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alerts_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alerts_resolved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("run_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('running','completed','failed','skipped')",
            name="ck_automation_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automation_runs_job_started",
        "automation_runs",
        ["job_name", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automation_alerts")
