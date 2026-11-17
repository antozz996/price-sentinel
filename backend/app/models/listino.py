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


# Origine di un prezzo in listino_master. I prezzi nati prima della colonna
# restano NULL: la loro origine non è ricostruibile con certezza.
ORIGINE_MODULO_FORNITORE = "modulo_fornitore"      # risposta approvata a un modulo prezzi
ORIGINE_FOGLIO_PREZZI = "foglio_prezzi"            # Listino Smart / foglio prezzi precaricato
ORIGINE_IMPORT_LISTINO = "import_listino"          # caricamento Excel/CSV del listino fornitore
ORIGINE_FATTURA = "fattura"                        # «inserisci a listino» dalla coda prodotti
ORIGINE_MANUALE = "manuale"                        # inserito o corretto a mano
ORIGINE_APPROVAZIONE_ANOMALIA = "approvazione_anomalia"
ORIGINE_ORDINE = "ordine"                          # prezzo nato da un ordine/ricevimento merce
ORIGINI_PREZZO = (
    ORIGINE_MODULO_FORNITORE, ORIGINE_FOGLIO_PREZZI, ORIGINE_IMPORT_LISTINO, ORIGINE_FATTURA,
    ORIGINE_MANUALE, ORIGINE_APPROVAZIONE_ANOMALIA, ORIGINE_ORDINE,
)


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
    unita_misura: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
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
    origine: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="Da dove nasce il prezzo (ORIGINI_PREZZO); NULL = prezzo nato prima della colonna",
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
