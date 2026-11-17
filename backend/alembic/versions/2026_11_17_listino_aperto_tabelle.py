"""Listino sempre aperto: link fisso del fornitore e modifiche di prezzo in attesa."""

from alembic import op
import sqlalchemy as sa

revision = "listino_aperto_tabelle"
down_revision = "listino_origine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "supplier_price_links" not in existing:
        op.create_table(
            "supplier_price_links",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("fornitore_id", sa.Integer, sa.ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("token_encrypted", sa.Text, nullable=True),
            sa.Column("attivo", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_by_id", sa.Integer, sa.ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revocato_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ultimo_accesso_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ultima_conferma_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_supplier_price_links_fornitore_id", "supplier_price_links", ["fornitore_id"])
        op.create_index("ix_supplier_price_links_token_hash", "supplier_price_links", ["token_hash"], unique=True)
        op.create_index("uq_supplier_price_link_attivo", "supplier_price_links", ["fornitore_id"],
                        unique=True, postgresql_where=sa.text("attivo"))
    if "supplier_price_changes" not in existing:
        op.create_table(
            "supplier_price_changes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("link_id", sa.Integer, sa.ForeignKey("supplier_price_links.id", ondelete="SET NULL"), nullable=True),
            sa.Column("fornitore_id", sa.Integer, sa.ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("sku_interno", sa.String(100), nullable=False),
            sa.Column("supplier_product_alias_id", sa.Integer,
                      sa.ForeignKey("supplier_product_aliases.id", ondelete="SET NULL"), nullable=True),
            sa.Column("chiave_offerta", sa.String(120), nullable=False),
            sa.Column("listino_id_origine", sa.Integer, sa.ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True),
            sa.Column("prezzo_vecchio", sa.Numeric(12, 4), nullable=True),
            sa.Column("prezzo_nuovo", sa.Numeric(12, 4), nullable=True),
            sa.Column("unita_misura", sa.String(50), nullable=True),
            sa.Column("tipo", sa.String(20), nullable=False),
            sa.Column("stato", sa.String(20), nullable=False),
            sa.Column("decorrenza", sa.Date, nullable=False),
            sa.Column("motivo_trattenuta", sa.String(200), nullable=True),
            sa.Column("nota_fornitore", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("applicato_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applicato_listino_id", sa.Integer, sa.ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True),
            sa.Column("sostituito_da_id", sa.Integer, sa.ForeignKey("supplier_price_changes.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decisione_by_id", sa.Integer, sa.ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True),
            sa.Column("decisione_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ip", sa.String(64), nullable=True),
        )
        for column in ("link_id", "fornitore_id", "stato", "decorrenza"):
            op.create_index(f"ix_supplier_price_changes_{column}", "supplier_price_changes", [column])
        op.create_index("uq_supplier_price_change_in_attesa", "supplier_price_changes",
                        ["fornitore_id", "chiave_offerta"], unique=True,
                        postgresql_where=sa.text("stato IN ('programmato', 'trattenuto')"))


def downgrade() -> None:
    op.drop_table("supplier_price_changes")
    op.drop_table("supplier_price_links")
