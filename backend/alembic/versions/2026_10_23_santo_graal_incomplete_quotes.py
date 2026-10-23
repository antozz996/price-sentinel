"""Allow Santo Graal prices before supplier unit and brand are known.

Revision ID: santo_graal_incomplete_quotes
Revises: supplier_safe_archiving
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "santo_graal_incomplete_quotes"
down_revision: Union[str, None] = "supplier_safe_archiving"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("products", "comparison_unit", existing_type=sa.String(length=50), nullable=True)
    op.alter_column("listino_master", "unita_misura", existing_type=sa.String(length=20), nullable=True)
    op.add_column("supplier_product_aliases", sa.Column("brand", sa.String(length=100), nullable=True))
    op.add_column("supplier_price_form_items", sa.Column("brand_corrente", sa.String(length=100), nullable=True))
    op.add_column("supplier_price_form_items", sa.Column("brand_inviata", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    product_missing = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM products WHERE comparison_unit IS NULL)")).scalar()
    price_missing = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM listino_master WHERE unita_misura IS NULL)")).scalar()
    if product_missing or price_missing:
        raise RuntimeError("Non è possibile ripristinare le unità obbligatorie: esistono dati senza unità confermata.")
    op.drop_column("supplier_price_form_items", "brand_inviata")
    op.drop_column("supplier_price_form_items", "brand_corrente")
    op.drop_column("supplier_product_aliases", "brand")
    op.alter_column("listino_master", "unita_misura", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("products", "comparison_unit", existing_type=sa.String(length=50), nullable=False)
