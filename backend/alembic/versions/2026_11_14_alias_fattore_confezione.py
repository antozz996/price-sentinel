"""Fattore confezione sul collegamento fornitore-prodotto (unità di listino per unità di fattura)."""

from alembic import op
import sqlalchemy as sa

revision = "alias_fattore_confezione"
down_revision = "form_best_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("supplier_product_aliases")}
    if "fattore_confezione" not in columns:
        op.add_column("supplier_product_aliases", sa.Column("fattore_confezione", sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_product_aliases", "fattore_confezione")
