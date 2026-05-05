"""
Price Sentinel — Modello Location.
Spec §5.1: Tabella Location — le 10 strutture del gruppo.
"""

import enum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TipologiaLocation(str, enum.Enum):
    """Tipologie struttura dal Master Spec."""
    balneare = "balneare"
    ristorante = "ristorante"
    discoteca = "discoteca"
    evento = "evento"


class Location(Base):
    __tablename__ = "location"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome_struttura: Mapped[str] = mapped_column(String(255), nullable=False)
    piva_riferimento: Mapped[str] = mapped_column(
        String(11),
        unique=True,
        nullable=False,
        index=True,
        comment="P.IVA della location",
    )
    tipologia: Mapped[TipologiaLocation] = mapped_column(
        Enum(TipologiaLocation, name="tipologia_location", native_enum=True),
        nullable=False,
    )

    # ── Relationships ────────────────────────
    utenti = relationship("Utente", back_populates="location", lazy="selectin")
    fatture = relationship("Fattura", back_populates="location", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Location {self.nome_struttura} ({self.piva_riferimento})>"
