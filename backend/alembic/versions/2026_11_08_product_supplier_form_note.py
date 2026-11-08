"""Per-product instructions shown to suppliers in the price form."""

from alembic import op
import sqlalchemy as sa

revision = "product_supplier_form_note"
down_revision = "supplier_form_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("products")}
    if "supplier_form_note" not in columns:
        op.add_column("products", sa.Column("supplier_form_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "supplier_form_note")
