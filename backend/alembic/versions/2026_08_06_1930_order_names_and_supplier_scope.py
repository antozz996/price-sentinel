"""add optional order search names

Revision ID: smart_order_names
Revises: smart_price_policy
Create Date: 2026-08-06 19:30:00+00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "smart_order_names"
down_revision: Union[str, None] = "smart_price_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("order_name", sa.String(120), nullable=True))
    op.add_column(
        "products", sa.Column("normalized_order_name", sa.String(120), nullable=True)
    )
    op.create_index(
        "uq_products_normalized_order_name",
        "products",
        ["normalized_order_name"],
        unique=True,
        postgresql_where=sa.text("normalized_order_name is not null"),
    )


def downgrade() -> None:
    op.drop_index("uq_products_normalized_order_name", table_name="products")
    op.drop_column("products", "normalized_order_name")
    op.drop_column("products", "order_name")
