from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ClipboardPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    supplier_mapping: dict[str, int] = Field(default_factory=dict)
    product_mapping: dict[str, int] = Field(default_factory=dict)
    effective_date: date = Field(default_factory=date.today)
    default_uom: str = Field(default="piece", min_length=1, max_length=20)
    location_id: int | None = Field(default=None, gt=0)


class CellPreviewRequest(BaseModel):
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    effective_date: date = Field(default_factory=date.today)
    uom: str = Field(default="piece", min_length=1, max_length=20)
    location_id: int | None = Field(default=None, gt=0)


class CommitPreviewRequest(BaseModel):
    preview_token: UUID
    confirm: bool


class SupplierSectorUpdateRequest(BaseModel):
    supplier_id: int = Field(gt=0)
    category: str = Field(min_length=1, max_length=100)
    mode: Literal["auto", "enabled", "disabled"]
    reason: str | None = Field(default=None, max_length=500)


class AssessmentUpsertRequest(BaseModel):
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    status: Literal["approved", "discouraged", "blocked"]
    quality_score: int = Field(ge=1, le=5)
    delivery_reliability_score: Decimal | None = Field(default=None, ge=0, le=100)
    reason: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    valid_from: date = Field(default_factory=date.today)
    valid_to: date | None = None

    @model_validator(mode="after")
    def require_reason(self):
        if self.status != "approved" and len((self.reason or "").strip()) < 3:
            raise ValueError("La motivazione è obbligatoria per sconsigliato o bloccato")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("La data finale non può precedere quella iniziale")
        return self


class PolicyUpsertRequest(BaseModel):
    product_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    selection_mode: Literal["manual", "best_eligible_price", "absolute_lowest"]
    preferred_supplier_id: int | None = Field(default=None, gt=0)
    minimum_quality: int = Field(default=1, ge=1, le=5)
    max_price_premium_percent: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=4)
    max_price_premium_absolute: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=4)
    allow_spot: bool = True
    reason: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    valid_from: date = Field(default_factory=date.today)
    valid_to: date | None = None

    @model_validator(mode="after")
    def manual_requires_supplier(self):
        if self.selection_mode == "manual" and self.preferred_supplier_id is None:
            raise ValueError("In modalità manuale il fornitore preferito è obbligatorio")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("La data finale non può precedere quella iniziale")
        return self


class DeviationCreateRequest(BaseModel):
    dedupe_key: str = Field(min_length=8, max_length=255)
    product_id: int = Field(gt=0)
    invoice_line_id: int | None = Field(default=None, gt=0)
    purchase_order_id: int | None = Field(default=None, gt=0)
    location_id: int | None = Field(default=None, gt=0)
    recommended_supplier_id: int | None = Field(default=None, gt=0)
    selected_supplier_id: int = Field(gt=0)
    absolute_cheapest_supplier_id: int | None = Field(default=None, gt=0)
    deviation_type: Literal[
        "non_preferred_supplier",
        "blocked_supplier",
        "discouraged_supplier",
        "quality_below_threshold",
        "premium_over_limit",
        "spot_not_allowed",
    ]
    actual_normalized_price: Decimal | None = Field(default=None, ge=0)
    absolute_cheapest_price: Decimal | None = Field(default=None, ge=0)
    recommended_price: Decimal | None = Field(default=None, ge=0)
    premium_amount: Decimal | None = Field(default=None, ge=0)
    premium_percent: Decimal | None = Field(default=None, ge=0)
    policy_snapshot: dict = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=2000)
    context: dict = Field(default_factory=dict)


class DeviationUpdateRequest(BaseModel):
    status: Literal["acknowledged", "accepted_exception", "resolved"]
    reason: str | None = Field(default=None, min_length=3, max_length=2000)


class AuditEntryResponse(BaseModel):
    entity_type: str
    entity_id: str
    action: str
    actor_id: int
    occurred_at: datetime
    before_state: dict | None = None
    after_state: dict | None = None
