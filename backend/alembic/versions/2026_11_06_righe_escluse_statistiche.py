"""Invoice lines kept as they are but excluded from reference prices."""

from alembic import op
import sqlalchemy as sa

revision = "righe_escluse_statistiche"
down_revision = "anomalie_archiviate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application creates missing tables at startup, so the table may already exist.
    if sa.inspect(op.get_bind()).has_table("righe_escluse_statistiche"):
        return
    op.create_table(
        "righe_escluse_statistiche",
        sa.Column(
            "riga_fattura_id",
            sa.Integer(),
            sa.ForeignKey("righe_fattura.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("motivo", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("righe_escluse_statistiche")
