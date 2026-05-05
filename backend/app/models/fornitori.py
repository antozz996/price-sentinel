"""
Price Sentinel — Modello Fornitori.
Spec §5.1: Tabella Fornitori con whitelist attiva.
"""

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Fornitore(Base):
    __tablename__ = "fornitori"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partita_iva: Mapped[str] = mapped_column(
        String(11),
        unique=True,
        nullable=False,
        index=True,
        comment="P.IVA cedente da XML",
    )
    nome_azienda: Mapped[str] = mapped_column(String(255), nullable=False)
    attivo_whitelist: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="FALSE = archiviazione passiva senza matching",
    )
    email_contatto: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Per generazione reclami",
    )

    # ── Relationships ────────────────────────
    listini = relationship("ListinoMaster", back_populates="fornitore", lazy="selectin")
    fatture = relationship("Fattura", back_populates="fornitore", lazy="selectin")
    alias = relationship("AliasProdotto", back_populates="fornitore", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Fornitore {self.nome_azienda} ({self.partita_iva})>"
