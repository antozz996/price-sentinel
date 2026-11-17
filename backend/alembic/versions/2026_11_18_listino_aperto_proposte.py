"""Listino sempre aperto: nomi corretti e prodotti nuovi proposti dal fornitore."""

from alembic import op
import sqlalchemy as sa

revision = "listino_aperto_proposte"
down_revision = "listino_aperto_tabelle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "supplier_product_proposals" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "supplier_product_proposals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("link_id", sa.Integer, sa.ForeignKey("supplier_price_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fornitore_id", sa.Integer, sa.ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("stato", sa.String(20), nullable=False),
        sa.Column("listino_id_origine", sa.Integer, sa.ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sku_interno", sa.String(100), nullable=True),
        sa.Column("supplier_product_alias_id", sa.Integer,
                  sa.ForeignKey("supplier_product_aliases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("nome_precedente", sa.String(255), nullable=True),
        sa.Column("nome_fornitore", sa.String(255), nullable=False),
        sa.Column("unita_vendita", sa.String(10), nullable=True),
        sa.Column("contenuto_quantita", sa.Numeric(12, 4), nullable=True),
        sa.Column("contenuto_unita", sa.String(10), nullable=True),
        sa.Column("prezzo", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("sostituita_da_id", sa.Integer,
                  sa.ForeignKey("supplier_product_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decisione_by_id", sa.Integer, sa.ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decisione_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applicato_alias_id", sa.Integer,
                  sa.ForeignKey("supplier_product_aliases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applicato_listino_id", sa.Integer,
                  sa.ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True),
    )
    for column in ("link_id", "fornitore_id", "stato"):
        op.create_index(f"ix_supplier_product_proposals_{column}", "supplier_product_proposals", [column])
    op.create_index("uq_supplier_product_proposal_nome", "supplier_product_proposals",
                    ["fornitore_id", "listino_id_origine"], unique=True,
                    postgresql_where=sa.text("tipo = 'nome' AND stato = 'in_attesa'"))


def downgrade() -> None:
    op.drop_table("supplier_product_proposals")
