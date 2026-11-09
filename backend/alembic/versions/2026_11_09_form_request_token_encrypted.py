"""Encrypted supplier form token, so a queued form link can be shared again."""

from alembic import op
import sqlalchemy as sa

revision = "form_request_token_encrypted"
down_revision = "form_item_offer_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("supplier_price_form_requests")}
    if "token_encrypted" not in columns:
        op.add_column("supplier_price_form_requests", sa.Column("token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_price_form_requests", "token_encrypted")
