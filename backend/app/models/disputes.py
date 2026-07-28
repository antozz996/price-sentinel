"""Auditable supplier dispute and credit-note workflow."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


CASE_STATUSES = (
    "draft",
    "ready_to_send",
    "sent",
    "supplier_replied",
    "credit_note_expected",
    "partially_recovered",
    "recovered",
    "rejected",
    "closed",
    "cancelled",
)


class DisputeCase(Base):
    __tablename__ = "dispute_cases"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft','ready_to_send','sent','supplier_replied',"
            "'credit_note_expected','partially_recovered','recovered',"
            "'rejected','closed','cancelled')",
            name="ck_dispute_cases_status",
        ),
        CheckConstraint(
            "requested_amount >= 0 and recognized_amount >= 0 "
            "and recovered_amount >= 0 and unrecovered_amount >= 0",
            name="ck_dispute_cases_amounts_nonnegative",
        ),
        CheckConstraint(
            "recognized_amount <= requested_amount "
            "and recovered_amount <= recognized_amount "
            "and unrecovered_amount = requested_amount - recovered_amount",
            name="ck_dispute_cases_amount_consistency",
        ),
        CheckConstraint(
            "(status not in ('closed','cancelled')) "
            "or length(btrim(coalesce(manual_close_reason,''))) >= 8",
            name="ck_dispute_cases_terminal_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    case_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    liquidstock_venue_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reconciliation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("purchase_order_reconciliations.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    requested_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    recognized_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    recovered_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    unrecovered_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    manual_close_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    anomalies = relationship(
        "DisputeCaseAnomaly",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    communications = relationship(
        "DisputeCommunication",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attachments = relationship(
        "DisputeAttachment",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    responses = relationship(
        "DisputeSupplierResponse",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    credit_notes = relationship(
        "DisputeCreditNote",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    audit_events = relationship(
        "DisputeAuditEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    supplier = relationship("Fornitore", lazy="selectin")
    location = relationship("Location", lazy="selectin")
    owner = relationship("Utente", foreign_keys=[owner_user_id], lazy="selectin")

    @property
    def supplier_name(self) -> str | None:
        return self.supplier.nome_azienda if self.supplier else None

    @property
    def location_name(self) -> str | None:
        return self.location.nome_struttura if self.location else None

    @property
    def owner_email(self) -> str | None:
        return self.owner.email if self.owner else None


class DisputeCaseAnomaly(Base):
    __tablename__ = "dispute_case_anomalies"
    __table_args__ = (
        CheckConstraint(
            "(reconciliation_anomaly_id is not null)::integer "
            "+ (legacy_anomaly_id is not null)::integer = 1",
            name="ck_dispute_case_anomalies_one_source",
        ),
        CheckConstraint(
            "claimed_amount > 0 and recognized_amount >= 0 "
            "and recovered_amount >= 0 and recognized_amount <= claimed_amount "
            "and recovered_amount <= recognized_amount",
            name="ck_dispute_case_anomalies_amounts",
        ),
        UniqueConstraint(
            "reconciliation_anomaly_id",
            name="uq_dispute_case_anomalies_reconciliation",
        ),
        UniqueConstraint("legacy_anomaly_id", name="uq_dispute_case_anomalies_legacy"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reconciliation_anomaly_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("purchase_order_reconciliation_anomalies.id", ondelete="RESTRICT"),
        index=True,
    )
    legacy_anomaly_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("anomalie.id", ondelete="RESTRICT"), index=True
    )
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    recognized_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    recovered_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=0
    )
    reason_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="anomalies")


class DisputeCommunication(Base):
    __tablename__ = "dispute_communications"
    __table_args__ = (
        CheckConstraint(
            "channel in ('whatsapp','email','pdf','copy')",
            name="ck_dispute_communications_channel",
        ),
        CheckConstraint(
            "status in ('prepared','copied','opened','sent_manual','confirmed',"
            "'response_received')",
            name="ck_dispute_communications_status",
        ),
        CheckConstraint(
            "message_hash ~ '^[0-9a-f]{64}$'",
            name="ck_dispute_communications_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="prepared")
    recipient: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(255))
    body_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    copied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_manual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="communications")


class DisputeAttachment(Base):
    __tablename__ = "dispute_attachments"
    __table_args__ = (
        CheckConstraint(
            "size_bytes > 0 and size_bytes <= 10485760",
            name="ck_dispute_attachments_size",
        ),
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_dispute_attachments_sha256",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="attachments")


class DisputeSupplierResponse(Base):
    __tablename__ = "dispute_supplier_responses"
    __table_args__ = (
        CheckConstraint(
            "channel in ('whatsapp','email','phone','portal','other')",
            name="ck_dispute_supplier_responses_channel",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    communication_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_communications.id", ondelete="SET NULL"),
    )
    attachment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_attachments.id", ondelete="SET NULL"),
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    responder_name: Mapped[str | None] = mapped_column(String(255))
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="responses")


class DisputeCreditNote(Base):
    __tablename__ = "dispute_credit_notes"
    __table_args__ = (
        CheckConstraint(
            "source in ('manual','imported')",
            name="ck_dispute_credit_notes_source",
        ),
        CheckConstraint(
            "status in ('received','verified','partially_allocated','allocated','rejected')",
            name="ck_dispute_credit_notes_status",
        ),
        CheckConstraint("total_amount > 0", name="ck_dispute_credit_notes_amount"),
        UniqueConstraint(
            "location_id",
            "supplier_id",
            "document_number",
            "issue_date",
            name="uq_dispute_credit_notes_document",
        ),
        UniqueConstraint("fattura_id", name="uq_dispute_credit_notes_invoice"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fattura_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fatture.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    document_number: Mapped[str] = mapped_column(String(100), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="credit_notes")
    allocations = relationship(
        "DisputeCreditNoteAllocation",
        back_populates="credit_note",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DisputeCreditNoteAllocation(Base):
    __tablename__ = "dispute_credit_note_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_dispute_credit_note_allocations_amount"),
        UniqueConstraint(
            "credit_note_id",
            "case_anomaly_id",
            name="uq_dispute_credit_note_allocations_item",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    credit_note_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_credit_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_anomaly_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dispute_case_anomalies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    credit_note = relationship("DisputeCreditNote", back_populates="allocations")


class DisputeAuditEvent(Base):
    __tablename__ = "dispute_audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dispute_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dispute_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    event_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case = relationship("DisputeCase", back_populates="audit_events")
