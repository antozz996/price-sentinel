from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupplierIdentityEquivalenceCreate(StrictModel):
    canonical_supplier_id: int = Field(gt=0)
    equivalent_supplier_id: int = Field(gt=0)
    reason: str = Field(min_length=8, max_length=1000)
    confirm: bool


class SupplierIdentityEquivalenceUpdate(StrictModel):
    is_active: bool
    reason: str = Field(min_length=8, max_length=1000)
    confirm: bool


class SupplierSearchResult(BaseModel):
    id: int
    name: str


class SupplierIdentityEquivalenceOut(BaseModel):
    id: int
    canonical_supplier_id: int
    canonical_supplier_name: str
    equivalent_supplier_id: int
    equivalent_supplier_name: str
    is_active: bool
    reason: str
    approved_by: int
    approved_by_email: str
    approved_at: datetime
    updated_by: int
    updated_by_email: str
    created_at: datetime
    updated_at: datetime


class SupplierIdentityEquivalenceAuditOut(BaseModel):
    id: int
    equivalence_id: int
    action: str
    canonical_supplier_id: int
    canonical_supplier_name: str
    equivalent_supplier_id: int
    equivalent_supplier_name: str
    is_active: bool
    reason: str
    actor_id: int
    actor_email: str
    occurred_at: datetime
