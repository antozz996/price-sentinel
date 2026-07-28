"""Readiness and per-location reconciliation settings."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LocationSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_tolerance_absolute: Decimal = Field(ge=0, le=1000000)
    price_tolerance_percent: Decimal = Field(ge=0, le=100)
    important_anomaly_threshold: Decimal = Field(gt=0, le=10000000)
    stalled_reconciliation_days: int = Field(ge=1, le=90)
    missing_credit_note_days: int = Field(ge=1, le=180)
    notifications_enabled: bool = True


class LocationSettingsOut(LocationSettingsInput):
    location_id: int
    configured: bool


class OnboardingReadinessOut(BaseModel):
    location_id: int
    location_name: str
    users: int
    suppliers: int
    suppliers_with_contact: int
    active_products: int
    approved_aliases: int
    price_lists: int
    liquidstock_venue_mapped: bool
    liquidstock_orders: int
    invoices: int
    reconciliations: int
    disputes: int
    settings_configured: bool
    settings: LocationSettingsOut
