"""Store multiple quoted packages for one supplier form product."""

from alembic import op
import sqlalchemy as sa

revision = "supplier_multiple_offers"
down_revision = "supplier_offer_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supplier_price_form_items", sa.Column("offerte_inviate", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_price_form_items", "offerte_inviate")
