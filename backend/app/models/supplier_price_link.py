"""Listino sempre aperto: link fisso del fornitore e modifiche di prezzo che invia.

Le modifiche non vanno subito in listino_master: un aumento vale solo dalla prossima
data fissa (1 o 15 del mese), e alcune modifiche restano sospese finché l'ufficio
non le guarda. Per questo vivono qui, e il listino riceve una riga solo quando
la modifica diventa valida (stato "applicato", con applicato_listino_id).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Tipo della modifica inviata dal fornitore.
TIPO_RIBASSO = "ribasso"
TIPO_AUMENTO = "aumento"
TIPO_INVARIATO = "invariato"
TIPO_NON_TRATTATO = "non_trattato"
TIPO_NUOVA_OFFERTA = "nuova_offerta"
TIPI_MODIFICA = (TIPO_RIBASSO, TIPO_AUMENTO, TIPO_INVARIATO, TIPO_NON_TRATTATO, TIPO_NUOVA_OFFERTA)

# Stato della modifica.
STATO_PROGRAMMATO = "programmato"   # valida dalla decorrenza, il job la applica
STATO_TRATTENUTO = "trattenuto"     # sospesa: serve il via libera dell'ufficio
STATO_APPLICATO = "applicato"       # scritta in listino_master
STATO_SOSTITUITO = "sostituito"     # superata da un caricamento successivo dello stesso prodotto
STATO_RIFIUTATO = "rifiutato"       # l'ufficio non l'ha accettata
STATI_MODIFICA = (STATO_PROGRAMMATO, STATO_TRATTENUTO, STATO_APPLICATO, STATO_SOSTITUITO, STATO_RIFIUTATO)
STATI_IN_ATTESA = (STATO_PROGRAMMATO, STATO_TRATTENUTO)


def offer_key(sku_interno: str, supplier_product_alias_id: int | None) -> str:
    """Identifica un'offerta del fornitore: stesso prodotto, stessa variante (alias)."""
    return f"{sku_interno}#{supplier_product_alias_id or ''}"


class SupplierPriceLink(Base):
    """Link fisso, senza scadenza, con cui il fornitore aggiorna i suoi prezzi."""

    __tablename__ = "supplier_price_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fornitore_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Stesso token cifrato col segreto dell'app, per poter ricondividere il link.
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    attivo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocato_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_accesso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ultimo invio o "confermo tutto invariato": oltre 30 giorni il listino va segnalato.
    ultima_conferma_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier = relationship("Fornitore", lazy="selectin")

    __table_args__ = (
        # Un solo link attivo per fornitore.
        Index("uq_supplier_price_link_attivo", "fornitore_id", unique=True,
              postgresql_where=text("attivo")),
    )


class SupplierPriceChange(Base):
    """Una modifica di prezzo inviata dal fornitore, con la sua decorrenza e il suo esito."""

    __tablename__ = "supplier_price_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_price_links.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fornitore_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sku_interno: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_product_alias_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_product_aliases.id", ondelete="SET NULL"), nullable=True
    )
    chiave_offerta: Mapped[str] = mapped_column(String(120), nullable=False)
    # Riga di listino che si voleva cambiare (vuota per un'offerta nuova).
    listino_id_origine: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True
    )
    prezzo_vecchio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    prezzo_nuovo: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    unita_misura: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    stato: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    decorrenza: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    motivo_trattenuta: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nota_fornitore: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applicato_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicato_listino_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("listino_master.id", ondelete="SET NULL"), nullable=True
    )
    sostituito_da_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("supplier_price_changes.id", ondelete="SET NULL"), nullable=True
    )
    decisione_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True
    )
    decisione_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        # Al massimo una modifica in attesa per offerta: conta l'ultimo caricamento.
        Index("uq_supplier_price_change_in_attesa", "fornitore_id", "chiave_offerta", unique=True,
              postgresql_where=text("stato IN ('programmato', 'trattenuto')")),
    )
