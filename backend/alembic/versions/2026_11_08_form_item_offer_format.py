"""Agreed offer format (quantity and wording) on supplier price form rows."""

from alembic import op
import sqlalchemy as sa

revision = "form_item_offer_format"
down_revision = "product_supplier_form_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("supplier_price_form_items")}
    if "quantita_corrente" not in columns:
        op.add_column("supplier_price_form_items", sa.Column("quantita_corrente", sa.Numeric(12, 3), nullable=True))
    if "dicitura_corrente" not in columns:
        op.add_column("supplier_price_form_items", sa.Column("dicitura_corrente", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_price_form_items", "dicitura_corrente")
    op.drop_column("supplier_price_form_items", "quantita_corrente")
