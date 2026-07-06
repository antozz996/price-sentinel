"""
Price Sentinel — Modelli Prodotti Canonici e Alias.
Gestione del Master Product Identity Layer per risolvere il mismatch dei nomi.
"""

from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    """
    Rappresenta il prodotto interno canonico.
    """
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_interno: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
    container_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    comparison_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    is_commodity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    aliases = relationship("SupplierProductAlias", back_populates="product", cascade="all, delete-orphan")
    equivalence_groups = relationship(
        "ProductEquivalenceGroup",
        secondary="product_equivalence_group_items",
        back_populates="products",
    )
    match_candidates = relationship("MatchCandidate", back_populates="product", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Product {self.canonical_name}>"


class SupplierProductAlias(Base):
    """
    Rappresenta come uno specifico fornitore chiama un prodotto.
    """
    __tablename__ = "supplier_product_aliases"
    __table_args__ = (
        UniqueConstraint("supplier_id", "supplier_code", name="uq_supplier_product_aliases_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    raw_description: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_description: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ean: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    pack_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="approved", server_default="approved")
    confidence_score: Mapped[float] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=1.00,
        server_default="1.00",
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    supplier = relationship("Fornitore", lazy="selectin")
    product = relationship("Product", back_populates="aliases", lazy="selectin")

    def __repr__(self) -> str:
        return f"<SupplierProductAlias {self.raw_description} -> Product ID {self.product_id}>"


class ProductEquivalenceGroup(Base):
    """
    Gruppi di equivalenza commerciale per commodity ed equivalenti commerciali.
    """
    __tablename__ = "product_equivalence_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comparison_unit: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    products = relationship(
        "Product",
        secondary="product_equivalence_group_items",
        back_populates="equivalence_groups",
    )

    def __repr__(self) -> str:
        return f"<ProductEquivalenceGroup {self.name}>"


class ProductEquivalenceGroupItem(Base):
    """
    Tabella ponte molti-a-molti tra equivalence groups e products.
    """
    __tablename__ = "product_equivalence_group_items"

    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("product_equivalence_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    )


class MatchCandidate(Base):
    """
    Buffer temporaneo per suggerimenti di matching prima della conferma umana.
    """
    __tablename__ = "match_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("righe_fattura.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="invoice_line",
        server_default="invoice_line",
    )
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    reason_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    block_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    product = relationship("Product", back_populates="match_candidates", lazy="selectin")
    invoice_line = relationship("RigaFattura", lazy="selectin")
    supplier = relationship("Fornitore", lazy="selectin")
    resolved_by = relationship("Utente", lazy="selectin")

    @property
    def candidate_product_id(self) -> int:
        return self.product_id

    @candidate_product_id.setter
    def candidate_product_id(self, value: int):
        self.product_id = value

    def __repr__(self) -> str:
        return f"<MatchCandidate Line ID {self.invoice_line_id} -> Product ID {self.product_id} (Score: {self.score})>"
