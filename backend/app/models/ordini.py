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
        String(20),
        nullable=False,
        default="bozza",  # bozza, inviato
    )

    # ── Relationships ────────────────────────
    fornitore = relationship("Fornitore")
    location = relationship("Location")
    righe = relationship("RigaOrdine", back_populates="ordine", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Ordine id={self.id} fornitore={self.fornitore_id} totale={self.spesa_totale}>"


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

    # ── Relationships ────────────────────────
    ordine = relationship("Ordine", back_populates="righe")

    def __repr__(self) -> str:
        return f"<RigaOrdine {self.sku_interno} qta={self.quantita} @ {self.prezzo_inserito}>"
