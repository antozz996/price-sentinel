"""
Price Sentinel — Modelli Fatture.
Spec §5.2: XMLRaw (storage immutabile), Fatture, RigheFattura.
"""

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StatoIngestion(str, enum.Enum):
    """Stati di elaborazione XML."""
    ricevuto = "ricevuto"
    parsato = "parsato"
    errore = "errore"


class TipoDocumento(str, enum.Enum):
    """Tipi documento FatturaPA — Spec §2.2."""
    TD01 = "TD01"  # Fattura
    TD04 = "TD04"  # Nota di Credito
    TD08 = "TD08"  # Nota di Debito


class StatoMatching(str, enum.Enum):
    """Stati del matching riga fattura — Spec §3.1."""
    matched = "matched"
    in_parking = "in_parking"
    no_match = "no_match"


class SourceIngestion(str, enum.Enum):
    """Sorgente del dato XML."""
    webhook = "webhook"
    upload_manuale = "upload_manuale"


class MarkerFattura(str, enum.Enum):
    """Marker visuale per le fatture."""
    nessuno = "nessuno"
    da_verificare = "da_verificare"
    verificata = "verificata"
    contestata = "contestata"
    approvata = "approvata"
    sospesa = "sospesa"


class StatoBatch(str, enum.Enum):
    """Stato di elaborazione di un batch di upload."""
    in_elaborazione = "in_elaborazione"
    completato = "completato"
    completato_con_errori = "completato_con_errori"


class XMLRaw(Base):
    """
    Storage immutabile dell'XML FatturaPA originale.
    Spec §2.2: idempotenza garantita tramite hash_idempotenza.
    Il payload NON viene mai modificato — audit trail completo.
    """
    __tablename__ = "xml_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="XML originale integro — audit immutabile",
    )
    nome_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hash_idempotenza: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="SHA256(piva+numero+data)",
    )
    source: Mapped[SourceIngestion] = mapped_column(
        Enum(SourceIngestion, name="source_ingestion", native_enum=True),
        nullable=False,
        default=SourceIngestion.webhook,
    )
    upload_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("upload_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )
    stato_ingestion: Mapped[StatoIngestion] = mapped_column(
        Enum(StatoIngestion, name="stato_ingestion", native_enum=True),
        nullable=False,
        default=StatoIngestion.ricevuto,
    )
    data_ricezione: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    errore_dettaglio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Dettaglio se stato=errore",
    )

    # ── Relationships ────────────────────────
    fatture = relationship("Fattura", back_populates="xml_raw", lazy="selectin", cascade="all, delete-orphan")
    batch = relationship("UploadBatch", back_populates="files")

    def __repr__(self) -> str:
        return f"<XMLRaw {self.hash_idempotenza[:12]}… ({self.stato_ingestion.value})>"


class UploadBatch(Base):
    """
    Sessione di upload manuale di uno o più file XML/ZIP.
    """
    __tablename__ = "upload_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("location.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="CASCADE"),
        nullable=False,
    )
    stato: Mapped[StatoBatch] = mapped_column(
        Enum(StatoBatch, name="stato_batch", native_enum=True),
        nullable=False,
        default=StatoBatch.in_elaborazione,
    )
    file_totali: Mapped[int] = mapped_column(Integer, default=0)
    file_elaborati: Mapped[int] = mapped_column(Integer, default=0)
    gia_presenti: Mapped[int] = mapped_column(Integer, default=0)
    errori_formato: Mapped[int] = mapped_column(Integer, default=0)
    anomalie_generate: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ────────────────────────
    files = relationship("XMLRaw", back_populates="batch")
    location = relationship("Location")
    user = relationship("Utente")


class Fattura(Base):
    """
    Fattura elettronica parsata.
    Spec §5.2: collegata a XMLRaw, Fornitore, Location.
    """
    __tablename__ = "fatture"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    xml_raw_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("xml_raw.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fornitore_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="P.IVA cessionario",
    )
    numero_documento: Mapped[str] = mapped_column(String(50), nullable=False)
    data_documento: Mapped[date] = mapped_column(Date, nullable=False)
    data_ricezione_sdi: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_documento: Mapped[TipoDocumento] = mapped_column(
        Enum(TipoDocumento, name="tipo_documento", native_enum=True),
        nullable=False,
    )
    totale_imponibile: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    marker: Mapped[MarkerFattura] = mapped_column(
        Enum(MarkerFattura, name="marker_fattura", native_enum=True, create_type=False),
        nullable=False,
        default=MarkerFattura.nessuno,
        server_default="nessuno",
    )

    # ── Relationships ────────────────────────
    xml_raw = relationship("XMLRaw", back_populates="fatture")
    fornitore = relationship("Fornitore", back_populates="fatture")
    location = relationship("Location", back_populates="fatture")
    righe = relationship("RigaFattura", back_populates="fattura", lazy="selectin", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Fattura {self.numero_documento} ({self.tipo_documento.value})>"


class RigaFattura(Base):
    """
    Singola riga di dettaglio fattura.
    Spec §5.2: prezzo normalizzato = PrezzoUnitario * (1 - Sconto/100).
    """
    __tablename__ = "righe_fattura"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fattura_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fatture.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    numero_linea: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Da XML NumeroLinea",
    )
    codice_fornitore_raw: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Dato grezzo da XML — immutabile",
    )
    descrizione_fornitore_raw: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Descrizione grezza da XML",
    )
    sku_interno: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="NULLABLE — popolato dopo matching",
    )
    prezzo_unitario_fatturato: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="PrezzoUnitario da XML",
    )
    sconto_percentuale: Mapped[float] = mapped_column(
        Numeric(6, 4),
        nullable=False,
        default=0,
        server_default="0",
        comment="Da ScontoMaggiorazione XML",
    )
    prezzo_netto_normalizzato: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo dopo sconto — base Delta",
    )
    quantita: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
    )
    unita_misura_fattura: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    aliquota_iva: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Solo per contabilita'",
    )
    is_omaggio: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    stato_matching: Mapped[StatoMatching] = mapped_column(
        Enum(StatoMatching, name="stato_matching", native_enum=True),
        nullable=False,
        default=StatoMatching.no_match,
    )

    # ── Relationships ────────────────────────
    fattura = relationship("Fattura", back_populates="righe")
    anomalie = relationship("Anomalia", back_populates="riga_fattura", lazy="selectin", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<RigaFattura L{self.numero_linea} @ {self.prezzo_netto_normalizzato}>"
