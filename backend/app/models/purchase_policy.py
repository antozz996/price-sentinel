"""Supplier assessments, purchase policies and Smart Price Sheet audit data."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductSupplierAssessment(Base):
    __tablename__ = "product_supplier_assessments"
    __table_args__ = (
        CheckConstraint(
            "status in ('approved','discouraged','blocked')",
            name="ck_product_supplier_assessments_status",
        ),
        CheckConstraint(
            "quality_score between 1 and 5",
            name="ck_product_supplier_assessments_quality",
        ),
        CheckConstraint(
            "delivery_reliability_score is null or "
            "delivery_reliability_score between 0 and 100",
            name="ck_product_supplier_assessments_reliability",
        ),
        CheckConstraint(
            "valid_to is null or valid_to >= valid_from",
            name="ck_product_supplier_assessments_validity",
        ),
        CheckConstraint(
            "status = 'approved' or coalesce(length(btrim(reason)), 0) >= 3",
            name="ck_product_supplier_assessments_reason",
        ),
        Index(
            "uq_product_supplier_assessment_global",
            "product_id",
            "supplier_id",
            unique=True,
            postgresql_where=text("location_id is null"),
        ),
        Index(
            "uq_product_supplier_assessment_location",
            "product_id",
            "supplier_id",
            "location_id",
            unique=True,
            postgresql_where=text("location_id is not null"),
        ),
        Index(
            "ix_product_supplier_assessments_lookup",
            "product_id",
            "location_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="approved")
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    delivery_reliability_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    valid_from: Mapped[date] = mapped_column(nullable=False, default=date.today)
    valid_to: Mapped[date | None] = mapped_column(nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductSupplierAssessmentAudit(Base):
    __tablename__ = "product_supplier_assessment_audits"
    __table_args__ = (
        CheckConstraint(
            "action in ('created','updated')",
            name="ck_product_supplier_assessment_audits_action",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_supplier_assessments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductPurchasePolicy(Base):
    __tablename__ = "product_purchase_policies"
    __table_args__ = (
        CheckConstraint(
            "selection_mode in ('manual','best_eligible_price','absolute_lowest')",
            name="ck_product_purchase_policies_mode",
        ),
        CheckConstraint(
            "minimum_quality between 1 and 5",
            name="ck_product_purchase_policies_quality",
        ),
        CheckConstraint(
            "max_price_premium_percent >= 0 and max_price_premium_absolute >= 0",
            name="ck_product_purchase_policies_premium",
        ),
        CheckConstraint(
            "selection_mode <> 'manual' or preferred_supplier_id is not null",
            name="ck_product_purchase_policies_manual_supplier",
        ),
        CheckConstraint(
            "valid_to is null or valid_to >= valid_from",
            name="ck_product_purchase_policies_validity",
        ),
        Index(
            "uq_product_purchase_policy_global",
            "product_id",
            unique=True,
            postgresql_where=text("location_id is null"),
        ),
        Index(
            "uq_product_purchase_policy_location",
            "product_id",
            "location_id",
            unique=True,
            postgresql_where=text("location_id is not null"),
        ),
        Index("ix_product_purchase_policies_lookup", "product_id", "location_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="CASCADE"), nullable=True
    )
    selection_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="best_eligible_price"
    )
    preferred_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=True
    )
    minimum_quality: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    max_price_premium_percent: Mapped[float] = mapped_column(
        Numeric(8, 4), nullable=False, server_default="0"
    )
    max_price_premium_absolute: Mapped[float] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="0"
    )
    allow_spot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    valid_from: Mapped[date] = mapped_column(nullable=False, default=date.today)
    valid_to: Mapped[date | None] = mapped_column(nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductPurchasePolicyAudit(Base):
    __tablename__ = "product_purchase_policy_audits"
    __table_args__ = (
        CheckConstraint(
            "action in ('created','updated')",
            name="ck_product_purchase_policy_audits_action",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_purchase_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchasePolicyDeviation(Base):
    __tablename__ = "purchase_policy_deviations"
    __table_args__ = (
        CheckConstraint(
            "deviation_type in ('non_preferred_supplier','blocked_supplier',"
            "'discouraged_supplier','quality_below_threshold','premium_over_limit',"
            "'spot_not_allowed')",
            name="ck_purchase_policy_deviations_type",
        ),
        CheckConstraint(
            "status in ('open','acknowledged','accepted_exception','resolved')",
            name="ck_purchase_policy_deviations_status",
        ),
        Index(
            "ix_purchase_policy_deviations_scope",
            "location_id",
            "product_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    invoice_line_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("righe_fattura.id", ondelete="SET NULL"), nullable=True
    )
    purchase_order_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ordini.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="SET NULL"), nullable=True
    )
    recommended_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=True
    )
    selected_supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False
    )
    actual_supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=False
    )
    deviation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", server_default="open")
    absolute_cheapest_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), nullable=True
    )
    actual_normalized_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    absolute_cheapest_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    recommended_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    premium_amount: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    premium_percent: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SmartPriceSheetPreview(Base):
    __tablename__ = "smart_price_sheet_previews"
    __table_args__ = (
        CheckConstraint(
            "status in ('ready','committed','expired')",
            name="ck_smart_price_sheet_previews_status",
        ),
        Index("ix_smart_price_sheet_previews_expiry", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    commit_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ready")
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
