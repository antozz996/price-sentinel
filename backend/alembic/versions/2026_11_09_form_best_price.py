"""Optional best market price shown to suppliers in the price form."""

from alembic import op
import sqlalchemy as sa

revision = "form_best_price"
down_revision = "form_request_token_encrypted"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "show_best_price" not in _columns("supplier_price_form_requests"):
        op.add_column("supplier_price_form_requests", sa.Column(
            "show_best_price", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    items = _columns("supplier_price_form_items")
    if "best_price" not in items:
        op.add_column("supplier_price_form_items", sa.Column("best_price", sa.Numeric(12, 4), nullable=True))
    if "best_price_unit" not in items:
        op.add_column("supplier_price_form_items", sa.Column("best_price_unit", sa.String(length=20), nullable=True))
    if "recipient_is_best" not in items:
        op.add_column("supplier_price_form_items", sa.Column("recipient_is_best", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_price_form_items", "recipient_is_best")
    op.drop_column("supplier_price_form_items", "best_price_unit")
    op.drop_column("supplier_price_form_items", "best_price")
    op.drop_column("supplier_price_form_requests", "show_best_price")
