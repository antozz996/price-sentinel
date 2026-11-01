"""Store the supplier's trade name and package quantity on submitted offers."""

from alembic import op
import sqlalchemy as sa

revision = "supplier_offer_details"
down_revision = "santo_graal_incomplete_quotes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supplier_price_form_items", sa.Column("dicitura_inviata", sa.Text(), nullable=True))
    op.add_column("supplier_price_form_items", sa.Column("quantita_inviata", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_price_form_items", "quantita_inviata")
    op.drop_column("supplier_price_form_items", "dicitura_inviata")
