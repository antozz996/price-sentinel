"""
Price Sentinel — Modello Utenti.
Spec §5.1: Tabella Utenti con ruoli Admin/Manager.
"""

import enum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RuoloUtente(str, enum.Enum):
    """Ruoli utente dal Master Spec."""
    admin = "admin"
    manager = "manager"


class Utente(Base):
    __tablename__ = "utenti"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ruolo: Mapped[RuoloUtente] = mapped_column(
        Enum(RuoloUtente, name="ruolo_utente", native_enum=True),
        nullable=False,
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("location.id", ondelete="SET NULL"),
        nullable=True,
        comment="NULL per Admin (vede tutto)",
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(50), 
        nullable=True, 
        comment="Chat ID per le notifiche Telegram dello Sprint 3"
    )
    attivo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Relationships ────────────────────────
    location = relationship("Location", back_populates="utenti", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Utente {self.email} ({self.ruolo.value})>"
