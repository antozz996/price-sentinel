"""Company details sent by a new supplier through the price form."""

from alembic import op
import sqlalchemy as sa

revision = "supplier_form_identities"
down_revision = "righe_escluse_statistiche"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The application creates missing tables at startup, so the table may already exist.
    if sa.inspect(op.get_bind()).has_table("supplier_price_form_identities"):
        return
    op.create_table(
        "supplier_price_form_identities",
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("supplier_price_form_requests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ragione_sociale", sa.String(length=255), nullable=False),
        sa.Column("partita_iva", sa.String(length=20), nullable=False),
        sa.Column("telefono_ordini", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("supplier_price_form_identities")
