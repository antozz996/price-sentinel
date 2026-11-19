"""Listino sempre aperto: prodotti della lista di settore che il fornitore non ha."""

from alembic import op
import sqlalchemy as sa

revision = "listino_aperto_assenti"
down_revision = "listino_aperto_proposte"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "supplier_product_absences" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "supplier_product_absences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("fornitore_id", sa.Integer, sa.ForeignKey("fornitori.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_interno", sa.String(100), nullable=False),
        sa.Column("link_id", sa.Integer, sa.ForeignKey("supplier_price_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_supplier_product_absence", "supplier_product_absences",
                    ["fornitore_id", "sku_interno"], unique=True)


def downgrade() -> None:
    op.drop_table("supplier_product_absences")
