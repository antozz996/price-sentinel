from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VenueMappingInput(StrictModel):
    liquidstock_venue_id: UUID
    location_id: int = Field(gt=0)


class AttachInvoiceInput(StrictModel):
    fattura_id: int = Field(gt=0)
    allow_reassociate: bool = False
    price_tolerance_absolute: Decimal = Field(default=Decimal("0.01"), ge=0)
    price_tolerance_percent: Decimal = Field(default=Decimal("1.0"), ge=0)


class ResolveItemInput(StrictModel):
    action: str = Field(pattern="^(confirm|ignore|create_anomaly)$")
    liquidstock_item_id: UUID | None = None
    product_id: int | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)


class CloseReconciliationInput(StrictModel):
    notes: str | None = Field(default=None, max_length=1000)


class ReconciliationStatusRequest(StrictModel):
    liquidstock_supplier_order_id: UUID


class ReconciliationStatusResponse(StrictModel):
    liquidstock_supplier_order_id: UUID
    reconciliation_id: UUID | None = None
    status: str
    invoice_id: int | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    anomalies_count: int = 0
    disputed_amount: Decimal | None = None
    updated_at: datetime


class OrderCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    liquidstock_supplier_order_id: UUID
    liquidstock_order_id: UUID
    liquidstock_venue_id: UUID
    venue_name_snapshot: str | None
    supplier_id: int | None
    supplier_name_snapshot: str
    status: str
    sent_at: datetime | None
    requested_delivery_date: date | None
    received_at: datetime | None
    reconciliation_id: UUID | None = None
    reconciliation_status: str | None = None
    fattura_id: int | None = None


class InvoiceCandidateOut(BaseModel):
    id: int
    fornitore_id: int
    location_id: int
    numero_documento: str
    data_documento: date
    totale_imponibile: Decimal
    already_associated_to: UUID | None = None
    suggestion_score: Decimal = Decimal("0")
    suggestion_reasons: list[str] = []


class ReconciliationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    liquidstock_item_id: UUID | None
    riga_fattura_id: int | None
    product_id: int | None
    order_product_name: str | None
    invoice_product_description: str | None
    ordered_package_note: str | None
    ordered_quantity: Decimal | None
    received_quantity: Decimal | None
    invoiced_quantity: Decimal | None
    ordered_unit: str | None
    invoiced_unit: str | None
    expected_unit_price: Decimal | None
    expected_price_source: str | None
    invoiced_unit_price: Decimal | None
    quantity_delta: Decimal | None
    price_delta: Decimal | None
    disputed_amount: Decimal | None
    match_status: str
    anomaly_type: str | None
    match_method: str | None
    match_confidence: Decimal
    match_reason: str | None
    candidate_evidence: dict | None
    notes: str | None


class ReconciliationAnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reconciliation_item_id: int | None
    fattura_id: int | None
    riga_fattura_id: int | None
    anomaly_type: str
    disputed_amount: Decimal | None
    evidence: dict
    workflow_status: str
    notes: str | None


class ReconciliationDetailOut(BaseModel):
    id: UUID
    liquidstock_supplier_order_id: UUID
    liquidstock_order_id: UUID
    supplier_id: int | None
    fattura_id: int | None
    venue_id: UUID
    status: str
    matching_confidence: Decimal
    reconciliation_version: int
    price_tolerance_absolute: Decimal
    price_tolerance_percent: Decimal
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    venue_name: str | None = None
    items: list[ReconciliationItemOut]
    anomalies: list[ReconciliationAnomalyOut]
