"""Per-location operational settings used by reconciliation and onboarding."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LocationReconciliationSettings(Base):
    __tablename__ = "location_reconciliation_settings"
    __table_args__ = (
        CheckConstraint(
            "price_tolerance_absolute >= 0 "
            "and price_tolerance_percent >= 0 "
            "and important_anomaly_threshold > 0",
            name="ck_location_reconciliation_settings_amounts",
        ),
        CheckConstraint(
            "stalled_reconciliation_days between 1 and 90 "
            "and missing_credit_note_days between 1 and 180",
            name="ck_location_reconciliation_settings_days",
        ),
    )

    location_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location.id", ondelete="CASCADE"),
        primary_key=True,
    )
    price_tolerance_absolute: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0.01")
    )
    price_tolerance_percent: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("1")
    )
    important_anomaly_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("50")
    )
    stalled_reconciliation_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    missing_credit_note_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7
    )
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
