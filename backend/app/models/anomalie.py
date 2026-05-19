"""
Price Sentinel — Modelli Anomalie e Note di Credito.
Spec §4.1: workflow a 7 stati per gestione discrepanze prezzi.
Spec §5.2: Anomalie con snapshot prezzi, NoteDiCredito con importo recuperato.
"""

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StatoValidazione(str, enum.Enum):
    """
    Ciclo di vita anomalia — Spec §4.1.
    7 stati con transizioni definite.
    """
    da_verificare = "da_verificare"
    in_parking = "in_parking"
    accettata = "accettata"
    proposta_aggiornamento = "proposta_aggiornamento"
    contestata = "contestata"
    in_reclamo = "in_reclamo"
    risolta = "risolta"


class Anomalia(Base):
    """
    Discrepanza tra prezzo fatturato e prezzo listino.
    Spec §5.2: snapshot dei prezzi al momento della rilevazione.
    delta_prezzo = differenza unitaria, delta_totale = delta * quantita.
    """
    __tablename__ = "anomalie"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    riga_fattura_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("righe_fattura.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    delta_prezzo: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Differenza assoluta per unita'",
    )
    delta_totale: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="delta * quantita",
    )
    prezzo_listino_snapshot: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo contratto al momento fattura",
    )
    prezzo_fatturato_snapshot: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Prezzo netto normalizzato",
    )
    stato_validazione: Mapped[StatoValidazione] = mapped_column(
        Enum(StatoValidazione, name="stato_validazione", native_enum=True),
        nullable=False,
        default=StatoValidazione.da_verificare,
    )
    nota_manager: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Obbligatoria se stato=accettata",
    )
    validato_da_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
        comment="Manager che ha agito",
    )
    validato_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    gestito_da_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )
    gestito_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ────────────────────────
    riga_fattura = relationship("RigaFattura", back_populates="anomalie")
    validato_da = relationship("Utente", foreign_keys=[validato_da_user_id], lazy="selectin")
    gestito_da = relationship("Utente", foreign_keys=[gestito_da_admin_id], lazy="selectin")
    note_di_credito = relationship("NotaDiCredito", back_populates="anomalia", lazy="selectin")

    @property
    def descrizione_orig(self) -> str | None:
        return self.riga_fattura.descrizione_fornitore_raw if self.riga_fattura else None

    @property
    def fornitore_nome(self) -> str | None:
        if self.riga_fattura and self.riga_fattura.fattura and self.riga_fattura.fattura.fornitore:
            return self.riga_fattura.fattura.fornitore.nome_azienda
        return None

    @property
    def quantita(self) -> float | None:
        return self.riga_fattura.quantita if self.riga_fattura else None

    @property
    def codice_fornitore(self) -> str | None:
        return self.riga_fattura.codice_fornitore_raw if self.riga_fattura else None

    def __repr__(self) -> str:
        return f"<Anomalia Δ{self.delta_prezzo} ({self.stato_validazione.value})>"


class NotaDiCredito(Base):
    """
    Registrazione nota di credito ricevuta dal fornitore.
    Spec §4.3: chiude l'anomalia e aggiorna il contatore Soldi Recuperati.
    """
    __tablename__ = "note_di_credito"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomalia_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("anomalie.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    importo_recuperato: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        comment="Importo NC ricevuta",
    )
    data_emissione_nc: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Data NC fornitore",
    )
    data_registrazione: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Data inserimento in sistema",
    )
    numero_nc: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Riferimento documento NC",
    )
    registrato_da_admin_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── Relationships ────────────────────────
    anomalia = relationship("Anomalia", back_populates="note_di_credito")
    registrato_da = relationship("Utente", lazy="selectin")

    def __repr__(self) -> str:
        return f"<NotaDiCredito €{self.importo_recuperato}>"


class ApprovazionePrezzo(Base):
    """
    Consente di archiviare gli aumenti di prezzo che l'amministratore 
    ha deciso di approvare manualmente per un dato mese.
    """
    __tablename__ = "approvazioni_prezzo"

    sku_interno: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        index=True,
    )
    descrizione_orig: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    mese: Mapped[str] = mapped_column(
        String(7),
        primary_key=True,
        comment="Formato YYYY-MM",
    )
    prezzo_approvato: Mapped[float] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    stato: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="APPROVATO",
        server_default="APPROVATO",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ApprovazionePrezzo {self.sku_interno} - {self.mese} @ {self.prezzo_approvato}>"

