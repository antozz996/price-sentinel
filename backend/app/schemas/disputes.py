"""API contracts for supplier disputes and credit-note recovery."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DisputeAnomalySelection(StrictModel):
    reconciliation_anomaly_id: int | None = None
    legacy_anomaly_id: int | None = None
    claimed_amount: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def one_source(self):
        if (self.reconciliation_anomaly_id is None) == (
            self.legacy_anomaly_id is None
        ):
            raise ValueError("exactly_one_anomaly_source_required")
        return self


class DisputeCreate(StrictModel):
    title: str = Field(min_length=3, max_length=255)
    owner_user_id: int | None = None
    due_date: date | None = None
    internal_notes: str | None = Field(default=None, max_length=10000)
    anomalies: list[DisputeAnomalySelection] = Field(min_length=1, max_length=200)


class DisputeUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=255)
    owner_user_id: int | None = None
    due_date: date | None = None
    internal_notes: str | None = Field(default=None, max_length=10000)


class DisputeTransition(StrictModel):
    expected_version: int = Field(ge=1)
    target_status: str
    reason: str | None = Field(default=None, max_length=5000)


class RecognitionAllocation(StrictModel):
    case_anomaly_id: int
    amount: Decimal = Field(ge=0)


class DisputeRecognition(StrictModel):
    expected_version: int = Field(ge=1)
    allocations: list[RecognitionAllocation] = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)


class CommunicationPrepare(StrictModel):
    channel: str
    recipient: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=255)
    body_override: str | None = Field(default=None, min_length=1, max_length=50000)


class CommunicationEvent(StrictModel):
    action: str


class SupplierResponseCreate(StrictModel):
    channel: str
    responder_name: str | None = Field(default=None, max_length=255)
    response_text: str = Field(min_length=1, max_length=50000)
    received_at: datetime
    communication_id: UUID | None = None
    attachment_id: UUID | None = None


class CreditNoteAllocationCreate(StrictModel):
    case_anomaly_id: int
    amount: Decimal = Field(gt=0)


class CreditNoteCreate(StrictModel):
    document_number: str = Field(min_length=1, max_length=100)
    issue_date: date
    total_amount: Decimal = Field(gt=0)
    source: str = "manual"
    fattura_id: int | None = None
    notes: str | None = Field(default=None, max_length=5000)
    allocations: list[CreditNoteAllocationCreate] = Field(
        min_length=1, max_length=200
    )


class DisputeAnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reconciliation_anomaly_id: int | None
    legacy_anomaly_id: int | None
    claimed_amount: Decimal
    recognized_amount: Decimal
    recovered_amount: Decimal
    reason_snapshot: str
    evidence_snapshot: dict
    created_at: datetime


class CommunicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: str
    status: str
    recipient: str | None
    subject: str | None
    body_snapshot: str
    prepared_at: datetime
    copied_at: datetime | None
    opened_at: datetime | None
    sent_manual_at: datetime | None
    confirmed_at: datetime | None
    response_received_at: datetime | None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    description: str | None
    created_at: datetime


class SupplierResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    communication_id: UUID | None
    attachment_id: UUID | None
    channel: str
    responder_name: str | None
    response_text: str
    received_at: datetime
    recorded_by: int


class CreditNoteAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_anomaly_id: int
    amount: Decimal


class CreditNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fattura_id: int | None
    source: str
    status: str
    document_number: str
    issue_date: date
    total_amount: Decimal
    notes: str | None
    allocations: list[CreditNoteAllocationOut] = Field(default_factory=list)
    created_at: datetime


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    action: str
    entity_type: str
    entity_id: str
    before_state: dict | None
    after_state: dict | None
    event_metadata: dict | None
    created_at: datetime


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_code: str
    location_id: int
    liquidstock_venue_id: UUID | None
    supplier_id: int
    reconciliation_id: UUID | None
    status: str
    title: str
    owner_user_id: int | None
    due_date: date | None
    internal_notes: str | None
    requested_amount: Decimal
    recognized_amount: Decimal
    recovered_amount: Decimal
    unrecovered_amount: Decimal
    manual_close_reason: str | None
    version: int
    created_by: int
    updated_by: int
    created_at: datetime
    updated_at: datetime
    anomalies: list[DisputeAnomalyOut] = Field(default_factory=list)
    communications: list[CommunicationOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    responses: list[SupplierResponseOut] = Field(default_factory=list)
    credit_notes: list[CreditNoteOut] = Field(default_factory=list)
    audit_events: list[AuditEventOut] = Field(default_factory=list)
    supplier_name: str | None = None
    location_name: str | None = None
    owner_email: str | None = None


class DisputeDashboardOut(BaseModel):
    total_anomalies: int
    total_detected: Decimal
    total_contested: Decimal
    total_recognized: Decimal
    total_recovered: Decimal
    total_outstanding: Decimal
    open_cases: int
    overdue_cases: int
    missing_credit_notes: int
    average_resolution_days: Decimal | None
    by_location: list[dict]
    by_supplier: list[dict]
    by_cause: list[dict]
    monthly_trend: list[dict]
