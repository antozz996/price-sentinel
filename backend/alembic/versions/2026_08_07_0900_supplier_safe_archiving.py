"""add safe supplier archiving

Revision ID: supplier_safe_archiving
Revises: smart_supplier_sectors
Create Date: 2026-08-07 09:00:00+02:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "supplier_safe_archiving"
down_revision: Union[str, None] = "smart_supplier_sectors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fornitori",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_fornitori_archived_at",
        "fornitori",
        ["archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fornitori_archived_at", table_name="fornitori")
    op.drop_column("fornitori", "archived_at")
