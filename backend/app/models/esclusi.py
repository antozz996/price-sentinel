from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

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
