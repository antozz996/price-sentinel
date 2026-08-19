"""
Price Sentinel — Modelli Ordine e RigaOrdine.
Pre-Order Price Optimization & Routing.
"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Ordine(Base):
    """
    Rappresenta un documento d'ordine d'acquisto ottimizzato preventivamente.
    """
    __tablename__ = "ordini"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fornitore_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer,
        default=1,
        nullable=True,
        comment="ID Azienda / Tenant"
    )
    settore: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    data_consegna: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    whatsapp_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    data_ordine: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    spesa_totale: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0.0,
    )
    stato: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="inviato",  # inviato, consegnato, riconciliato
    )
    stato_ricezione: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="da_ricevere",  # da_ricevere, ricevuto_conforme, ricevuto_parziale, ricevuto_con_riserva
    )
    data_ricezione: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ricevuto_da_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )
    note_ricezione: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── Relationships ────────────────────────
    fornitore = relationship("Fornitore", lazy="selectin")
    location = relationship("Location", lazy="selectin")
    user = relationship("Utente", foreign_keys=[user_id], lazy="selectin")
    ricevuto_da = relationship("Utente", foreign_keys=[ricevuto_da_id], lazy="selectin")
    righe = relationship("RigaOrdine", back_populates="ordine", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Ordine id={self.id} fornitore={self.fornitore_id} totale={self.spesa_totale} stato_ricezione={self.stato_ricezione}>"


class RigaOrdine(Base):
    """
    Rappresenta un singolo articolo all'interno dell'ordine d'acquisto.
    """
    __tablename__ = "righe_ordine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ordine_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("ordini.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    sku_interno: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    descrizione: Mapped[str] = mapped_column(Text, nullable=False)
    quantita: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    quantita_ricevuta: Mapped[float | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    uom: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default="CT",
    )
    prezzo_pattuito: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo concordato o miglior spot di riferimento",
    )
    prezzo_inserito: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo effettivamente inserito dal buyer",
    )
    stato_ottimizzazione: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="ottimale",  # concordato, spot_ottimale, anomalo
    )
    stato_riga: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="in_attesa",  # conforme, parziale, mancante, danneggiato
    )
    note_riga: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── Relationships ────────────────────────
    ordine = relationship("Ordine", back_populates="righe")
    product = relationship("Product", lazy="selectin")

    def __repr__(self) -> str:
        return f"<RigaOrdine {self.sku_interno} qta={self.quantita} ricevuta={self.quantita_ricevuta} stato={self.stato_riga}>"
