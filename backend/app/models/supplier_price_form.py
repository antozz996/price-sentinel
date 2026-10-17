from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SupplierPriceFormRequest(Base):
    """A one-supplier, expiring link to confirm or propose listino values."""

    __tablename__ = "supplier_price_form_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    request_type: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmation", server_default="confirmation")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    validita_inviata_da: Mapped[date | None] = mapped_column(Date, nullable=True)
    validita_inviata_a: Mapped[date | None] = mapped_column(Date, nullable=True)

    supplier = relationship("Fornitore", lazy="selectin")
    items: Mapped[list["SupplierPriceFormItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )


class SupplierPriceFormItem(Base):
    """Snapshot of one agreed listino row plus the supplier's submitted answer."""

    __tablename__ = "supplier_price_form_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("supplier_price_form_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    listino_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listino_master.id", ondelete="RESTRICT"), nullable=True
    )
    sku_interno: Mapped[str] = mapped_column(String(100), nullable=False)
    descrizione: Mapped[str] = mapped_column(Text, nullable=False)
    prezzo_corrente: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    unita_corrente: Mapped[str | None] = mapped_column(String(50), nullable=True)
    validita_corrente_da: Mapped[date | None] = mapped_column(Date, nullable=True)
    validita_corrente_a: Mapped[date | None] = mapped_column(Date, nullable=True)

    prezzo_inviato: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    unita_inviata: Mapped[str | None] = mapped_column(String(50), nullable=True)
    conferma_prezzo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nota_fornitore: Mapped[str | None] = mapped_column(Text, nullable=True)

    request = relationship("SupplierPriceFormRequest", back_populates="items")

