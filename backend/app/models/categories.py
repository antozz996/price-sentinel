"""
Price Sentinel — Master Categories Model.
Gestione delle Categorie Master per cataloghi, fornitori e matching.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MasterCategory(Base):
    """
    Rappresenta una categoria master/settore merci (es. Beverage, Birre, Monouso, ecc.)
    """
    __tablename__ = "master_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    descrizione: Mapped[str | None] = mapped_column(Text, nullable=True)
    colore: Mapped[str | None] = mapped_column(String(30), nullable=True, default="#3b82f6")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
