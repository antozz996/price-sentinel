"""
Price Sentinel — Modello ProductFeedback.
Recensioni e segnalazioni qualità prodotti da parte dei responsabili di settore.
"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProductFeedback(Base):
    __tablename__ = "product_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="CASCADE"),
        nullable=False,
    )
    feedback: Mapped[str] = mapped_column(
        String(10),
        nullable=False,  # "SI" o "NO"
    )
    rating: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,  # 1-5 stelle
    )
    motivo: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    stato: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="in_attesa",  # in_attesa, escluso, archiviato
        index=True,
    )
    ordine_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("ordini.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="SET NULL"),
        nullable=True,
    )
    admin_action: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    admin_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── Relationships ────────────────────────
    product = relationship("Product", lazy="selectin")
    user = relationship("Utente", foreign_keys=[user_id], lazy="selectin")
    resolved_by = relationship("Utente", foreign_keys=[resolved_by_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<ProductFeedback id={self.id} product_id={self.product_id} feedback={self.feedback} stato={self.stato}>"
