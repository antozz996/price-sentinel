"""Allow Santo Graal prices before supplier unit and brand are known.

Revision ID: santo_graal_incomplete_quotes
Revises: supplier_safe_archiving
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "santo_graal_incomplete_quotes"
down_revision: Union[str, None] = "supplier_safe_archiving"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # V2 originally created these tables through SQLAlchemy metadata during
    # staging startup, so the V1 migration chain does not contain them.  A
    # production upgrade must be self-contained and must not depend on an
    # application process having called Base.metadata.create_all().
    if not inspector.has_table("supplier_price_form_requests"):
        op.create_table(
            "supplier_price_form_requests",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("supplier_id", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "request_type",
                sa.String(length=30),
                server_default="confirmation",
                nullable=False,
            ),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("validita_inviata_da", sa.Date(), nullable=True),
            sa.Column("validita_inviata_a", sa.Date(), nullable=True),
            sa.ForeignKeyConstraint(["created_by_id"], ["utenti.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["supplier_id"], ["fornitori.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_supplier_price_form_requests_supplier_id",
            "supplier_price_form_requests",
            ["supplier_id"],
        )
        op.create_index(
            "ix_supplier_price_form_requests_token_hash",
            "supplier_price_form_requests",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            "ix_supplier_price_form_requests_status",
            "supplier_price_form_requests",
            ["status"],
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("supplier_price_form_items"):
        op.create_table(
            "supplier_price_form_items",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("request_id", sa.Integer(), nullable=False),
            sa.Column("listino_id", sa.Integer(), nullable=True),
            sa.Column("sku_interno", sa.String(length=100), nullable=False),
            sa.Column("descrizione", sa.Text(), nullable=False),
            sa.Column("prezzo_corrente", sa.Numeric(12, 4), nullable=True),
            sa.Column("unita_corrente", sa.String(length=50), nullable=True),
            sa.Column("validita_corrente_da", sa.Date(), nullable=True),
            sa.Column("validita_corrente_a", sa.Date(), nullable=True),
            sa.Column("prezzo_inviato", sa.Numeric(12, 4), nullable=True),
            sa.Column("unita_inviata", sa.String(length=50), nullable=True),
            sa.Column("conferma_prezzo", sa.Boolean(), nullable=True),
            sa.Column("nota_fornitore", sa.Text(), nullable=True),
            sa.Column("non_trattato", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.ForeignKeyConstraint(["listino_id"], ["listino_master.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(
                ["request_id"],
                ["supplier_price_form_requests.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_supplier_price_form_items_request_id",
            "supplier_price_form_items",
            ["request_id"],
        )

    op.alter_column("products", "comparison_unit", existing_type=sa.String(length=50), nullable=True)
    op.alter_column("listino_master", "unita_misura", existing_type=sa.String(length=20), nullable=True)
    op.add_column("supplier_product_aliases", sa.Column("brand", sa.String(length=100), nullable=True))
    op.add_column("supplier_price_form_items", sa.Column("brand_corrente", sa.String(length=100), nullable=True))
    op.add_column("supplier_price_form_items", sa.Column("brand_inviata", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    product_missing = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM products WHERE comparison_unit IS NULL)")).scalar()
    price_missing = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM listino_master WHERE unita_misura IS NULL)")).scalar()
    if product_missing or price_missing:
        raise RuntimeError("Non è possibile ripristinare le unità obbligatorie: esistono dati senza unità confermata.")
    op.drop_table("supplier_price_form_items")
    op.drop_table("supplier_price_form_requests")
    op.drop_column("supplier_product_aliases", "brand")
    op.alter_column("listino_master", "unita_misura", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("products", "comparison_unit", existing_type=sa.String(length=50), nullable=False)
