"""Keep a full copy of every anomaly removed from the operational table."""

from alembic import op
import sqlalchemy as sa

revision = "anomalie_archiviate"
down_revision = "supplier_multiple_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application creates missing tables at startup, so the table may already exist.
    if sa.inspect(op.get_bind()).has_table("anomalie_archiviate"):
        return
    op.create_table(
        "anomalie_archiviate",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("anomalia_id", sa.Integer(), nullable=False),
        sa.Column(
            "riga_fattura_id",
            sa.Integer(),
            sa.ForeignKey("righe_fattura.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stato_validazione", sa.String(length=40), nullable=False),
        sa.Column("delta_totale", sa.Numeric(12, 4), nullable=False),
        sa.Column("motivo", sa.String(length=60), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("archiviata_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_anomalie_archiviate_anomalia_id", "anomalie_archiviate", ["anomalia_id"])
    op.create_index("ix_anomalie_archiviate_riga_fattura_id", "anomalie_archiviate", ["riga_fattura_id"])


def downgrade() -> None:
    op.drop_index("ix_anomalie_archiviate_riga_fattura_id", table_name="anomalie_archiviate")
    op.drop_index("ix_anomalie_archiviate_anomalia_id", table_name="anomalie_archiviate")
    op.drop_table("anomalie_archiviate")
