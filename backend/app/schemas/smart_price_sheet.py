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


class AssessmentUpsertRequest(BaseModel):
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    status: Literal["approved", "discouraged", "blocked"]
    quality_score: int = Field(ge=1, le=5)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_reason(self):
        if self.status != "approved" and len((self.reason or "").strip()) < 3:
            raise ValueError("La motivazione è obbligatoria per sconsigliato o bloccato")
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
    notes: str | None = Field(default=None, max_length=2000)


class DeviationCreateRequest(BaseModel):
    dedupe_key: str = Field(min_length=8, max_length=255)
    product_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    recommended_supplier_id: int | None = Field(default=None, gt=0)
    selected_supplier_id: int = Field(gt=0)
    deviation_type: Literal[
        "manual_override",
        "blocked_supplier",
        "discouraged_supplier",
        "quality_below_minimum",
        "premium_exceeded",
        "spot_not_allowed",
    ]
    reason: str = Field(min_length=3, max_length=2000)
    context: dict = Field(default_factory=dict)


class AuditEntryResponse(BaseModel):
    entity_type: str
    entity_id: str
    action: str
    actor_id: int
    occurred_at: datetime
    before_state: dict | None = None
    after_state: dict | None = None
