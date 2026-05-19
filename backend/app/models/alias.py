"""
Price Sentinel — Modello AliasProdotti.
Spec §5.2: mappatura codice fornitore → SKU interno.
Tabella dinamica che migliora nel tempo con le conferme degli operatori.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AliasProdotto(Base):
    """
    Alias tra codice fornitore originale e SKU interno.
    Spec §3.1: usato nel Livello 1 del matching (match esatto su CodiceArticolo).
    Confermato dall'operatore → salvato permanentemente.
    """
    __tablename__ = "alias_prodotti"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fornitore_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    codice_fornitore_originale: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    sku_interno: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    coefficiente_conversione: Mapped[float] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        default=1.0,
        server_default="1.0",
        comment="Fattore conversione quantita/prezzo (es. 6 se cassa da 6pz)",
    )
    confermato_da_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
        comment="Chi ha creato l'alias",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # ── Relationships ────────────────────────
    fornitore = relationship("Fornitore", back_populates="alias")
    confermato_da = relationship("Utente", lazy="selectin")

    def __repr__(self) -> str:
        return f"<AliasProdotto {self.codice_fornitore_originale} → {self.sku_interno}>"
