"""add explicit supplier category capabilities

Revision ID: smart_supplier_sectors
Revises: smart_order_names
Create Date: 2026-08-06 20:30:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "smart_supplier_sectors"
down_revision: Union[str, None] = "smart_order_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_category_capabilities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["utenti.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_id", "category", name="uq_supplier_category_capability"
        ),
    )
    op.create_index(
        "ix_supplier_category_capabilities_supplier",
        "supplier_category_capabilities",
        ["supplier_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_table("supplier_category_capabilities")
