from datetime import datetime, timezone
from sqlalchemy import ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class RigaEsclusaStatistiche(Base):
    """
    Riga fattura reale ma esclusa dai prezzi di riferimento (minimo storico,
    spreco, rincari), per esempio un evidente errore di fatturazione.
    La riga e la fattura restano invariate.
    """
    __tablename__ = "righe_escluse_statistiche"

    riga_fattura_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("righe_fattura.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    motivo: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

class SKUEscluso(Base):
    """
    Prodotti/SKU esclusi globalmente dall'analisi, dai grafici e dalle anomalie.
    """
    __tablename__ = "skus_esclusi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_interno: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<SKUEscluso {self.sku_interno}>"
