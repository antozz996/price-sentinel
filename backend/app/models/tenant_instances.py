from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TenantInstance(Base):
    """
    Registro delle istanze aziendali attivate (Multi-Istanza / White-Label).
    """
    __tablename__ = "tenant_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    frontend_port: Mapped[int] = mapped_column(Integer, nullable=False)
    backend_port: Mapped[int] = mapped_column(Integer, nullable=False)
    db_port: Mapped[int] = mapped_column(Integer, nullable=False)
    access_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
