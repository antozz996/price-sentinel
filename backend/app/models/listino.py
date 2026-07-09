"""
Price Sentinel — Modelli Listino.
Spec §5.1: ListinoMaster (Append-Only), PFAScaglioni, UoMConversioni.
"""

import enum
from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PFATipo(str, enum.Enum):
    """Tipi di Premio Fine Anno dal Master Spec §3.4."""
    percentuale = "percentuale"
    fisso = "fisso"
    scaglioni = "scaglioni"


class ListinoMaster(Base):
    """
    Listino prezzi concordati — APPEND-ONLY.
    Nessun record viene mai modificato o cancellato.
    data_scadenza NULL = record attivo corrente.
    """
    __tablename__ = "listino_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fornitore_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sku_interno: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    descrizione: Mapped[str] = mapped_column(Text, nullable=False)
    prezzo_pattuito: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo netto contratto",
    )
    unita_misura: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Es. Kg, Lt, Pz, Cassa",
    )
    data_inizio_validita: Mapped[date] = mapped_column(Date, nullable=False)
    data_scadenza: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="NULL = record attivo corrente",
    )
    pfa_tipo: Mapped[PFATipo | None] = mapped_column(
        Enum(PFATipo, name="pfa_tipo", native_enum=True),
        nullable=True,
    )
    pfa_valore: Mapped[float | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
        comment="Solo per tipo Percentuale e Fisso",
    )
    supplier_product_alias_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("supplier_product_aliases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Relationships ────────────────────────
    fornitore = relationship("Fornitore", back_populates="listini")
    supplier_product_alias = relationship("SupplierProductAlias")
    pfa_scaglioni = relationship("PFAScaglione", back_populates="listino", lazy="selectin")
    uom_conversioni = relationship("UoMConversione", back_populates="listino", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ListinoMaster {self.sku_interno} @ {self.prezzo_pattuito}>"


class PFAScaglione(Base):
    """
    Scaglioni del Premio Fine Anno.
    Spec §3.4: soglie progressive con percentuali crescenti.
    soglia_a NULL = oltre soglia_da (ultimo scaglione).
    """
    __tablename__ = "pfa_scaglioni"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listino_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("listino_master.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    soglia_da: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        comment="Euro fatturato da",
    )
    soglia_a: Mapped[float | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
        comment="NULL = oltre soglia_da",
    )
    valore_percentuale: Mapped[float] = mapped_column(
        Numeric(6, 4),
        nullable=False,
        comment="Es. 0.0150 = 1.5%",
    )

    # ── Relationships ────────────────────────
    listino = relationship("ListinoMaster", back_populates="pfa_scaglioni")

    def __repr__(self) -> str:
        return f"<PFAScaglione {self.soglia_da}-{self.soglia_a} @ {self.valore_percentuale}>"


class UoMConversione(Base):
    """
    Conversioni unità di misura per fornitore/prodotto.
    Spec §3.2: coefficiente per normalizzazione prezzi fattura vs listino.
    """
    __tablename__ = "uom_conversioni"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listino_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("listino_master.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uom_fattura: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Unita' come arriva in fattura",
    )
    coefficiente: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        comment="Es. 5 per Cassa da 5Kg",
    )

    # ── Relationships ────────────────────────
    listino = relationship("ListinoMaster", back_populates="uom_conversioni")

    def __repr__(self) -> str:
        return f"<UoMConversione {self.uom_fattura} x{self.coefficiente}>"
