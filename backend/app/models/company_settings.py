from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CompanySettings(Base):
    """
    Impostazioni aziendali per White-Label e Multi-Istanza (Nome azienda, Sottotitolo, Logo, Contatti).
    """
    __tablename__ = "company_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Price Sentinel")
    app_subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="Audit & Purchasing Platform")
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primary_color: Mapped[str] = mapped_column(String(50), nullable=False, default="#3b82f6")
    support_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="support@pricesentinel.it")
    currency_symbol: Mapped[str] = mapped_column(String(10), nullable=False, default="€")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
