"""Origine del prezzo in listino_master e indice per fornitore, voce e decorrenza."""

from alembic import op
import sqlalchemy as sa

revision = "listino_origine"
down_revision = "fatture_xml_raw_unico"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("listino_master")}
    if "origine" not in columns:
        op.add_column("listino_master", sa.Column("origine", sa.String(30), nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_listino_fornitore_sku_inizio "
        "ON listino_master (fornitore_id, sku_interno, data_inizio_validita)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_listino_fornitore_sku_inizio")
    op.drop_column("listino_master", "origine")
