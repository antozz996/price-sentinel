"""Order/invoice reconciliation models isolated from legacy anomalies."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LiquidStockVenueMapping(Base):
    __tablename__ = "liquidstock_venue_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    liquidstock_venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("location.id", ondelete="RESTRICT"), nullable=False, unique=True)
    venue_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PurchaseOrderReconciliation(Base):
    __tablename__ = "purchase_order_reconciliations"
    __table_args__ = (
        CheckConstraint("status in ('pending','awaiting_invoice','matching','partially_matched','matched','anomalies_found','reviewed','closed')", name="ck_po_reconciliations_status"),
        CheckConstraint("matching_confidence >= 0 and matching_confidence <= 1", name="ck_po_reconciliations_confidence"),
        CheckConstraint("price_tolerance_absolute >= 0 and price_tolerance_percent >= 0", name="ck_po_reconciliations_tolerances"),
        CheckConstraint(
            """
            (
              fattura_id is null
              and invoice_supplier_id is null
              and supplier_equivalence_id is null
              and supplier_equivalence_approved_by is null
              and supplier_equivalence_approved_at is null
              and supplier_equivalence_used_at is null
              and supplier_equivalence_reason_snapshot is null
            )
            or
            (
              fattura_id is not null
              and invoice_supplier_id is not null
              and (
                (
                  supplier_id = invoice_supplier_id
                  and supplier_equivalence_id is null
                  and supplier_equivalence_approved_by is null
                  and supplier_equivalence_approved_at is null
                  and supplier_equivalence_used_at is null
                  and supplier_equivalence_reason_snapshot is null
                )
                or
                (
                  supplier_id <> invoice_supplier_id
                  and supplier_equivalence_id is not null
                  and supplier_equivalence_approved_by is not null
                  and supplier_equivalence_approved_at is not null
                  and supplier_equivalence_used_at is not null
                  and supplier_equivalence_reason_snapshot is not null
                )
              )
            )
            """,
            name="ck_po_reconciliations_supplier_identity_audit",
        ),
        UniqueConstraint("liquidstock_supplier_order_id", name="uq_po_reconciliations_supplier_order"),
        UniqueConstraint("fattura_id", name="uq_po_reconciliations_invoice"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    liquidstock_supplier_order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    liquidstock_order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), index=True)
    invoice_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), index=True
    )
    supplier_equivalence_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("supplier_identity_equivalences.id", ondelete="RESTRICT"),
        index=True,
    )
    supplier_equivalence_approved_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("utenti.id", ondelete="RESTRICT")
    )
    supplier_equivalence_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    supplier_equivalence_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    supplier_equivalence_reason_snapshot: Mapped[str | None] = mapped_column(Text)
    fattura_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fatture.id", ondelete="RESTRICT"), index=True)
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="awaiting_invoice")
    matching_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, default=0)
    reconciliation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_tolerance_absolute: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0.01"))
    price_tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("1.0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    items = relationship("PurchaseOrderReconciliationItem", back_populates="reconciliation", cascade="all, delete-orphan", lazy="selectin")
    anomalies = relationship("PurchaseOrderReconciliationAnomaly", back_populates="reconciliation", cascade="all, delete-orphan", lazy="selectin")
    invoice = relationship("Fattura", lazy="selectin")
    supplier = relationship(
        "Fornitore", foreign_keys=[supplier_id], lazy="selectin"
    )
    invoice_supplier = relationship(
        "Fornitore", foreign_keys=[invoice_supplier_id], lazy="selectin"
    )
    supplier_equivalence = relationship(
        "SupplierIdentityEquivalence", lazy="selectin"
    )
    supplier_equivalence_approver = relationship(
        "Utente",
        foreign_keys=[supplier_equivalence_approved_by],
        lazy="selectin",
    )


class PurchaseOrderReconciliationItem(Base):
    __tablename__ = "purchase_order_reconciliation_items"
    __table_args__ = (
        CheckConstraint("match_status in ('matched','quantity_mismatch','price_mismatch','unit_mismatch','unordered_item','missing_invoice_item','ambiguous','ignored')", name="ck_po_reconciliation_items_status"),
        CheckConstraint("match_confidence >= 0 and match_confidence <= 1", name="ck_po_reconciliation_items_confidence"),
        UniqueConstraint("reconciliation_id", "liquidstock_item_id", "riga_fattura_id", name="uq_po_reconciliation_item_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reconciliation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("purchase_order_reconciliations.id", ondelete="CASCADE"), nullable=False, index=True)
    liquidstock_item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    riga_fattura_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("righe_fattura.id", ondelete="RESTRICT"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    order_product_name: Mapped[str | None] = mapped_column(Text)
    invoice_product_description: Mapped[str | None] = mapped_column(Text)
    ordered_package_note: Mapped[str | None] = mapped_column(Text)
    ordered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    received_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    invoiced_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ordered_unit: Mapped[str | None] = mapped_column(String(100))
    invoiced_unit: Mapped[str | None] = mapped_column(String(100))
    expected_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    expected_price_source: Mapped[str | None] = mapped_column(String(80))
    invoiced_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    price_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    disputed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    match_status: Mapped[str] = mapped_column(String(40), nullable=False)
    anomaly_type: Mapped[str | None] = mapped_column(String(50))
    match_method: Mapped[str | None] = mapped_column(String(50))
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False, default=0)
    match_reason: Mapped[str | None] = mapped_column(Text)
    match_alias_supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"), index=True
    )
    candidate_evidence: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    reconciliation = relationship("PurchaseOrderReconciliation", back_populates="items")
    invoice_line = relationship("RigaFattura", lazy="selectin")
    product = relationship("Product", lazy="selectin")
    match_alias_supplier = relationship(
        "Fornitore", foreign_keys=[match_alias_supplier_id], lazy="selectin"
    )

    @property
    def match_alias_supplier_name(self) -> str | None:
        if not self.match_alias_supplier:
            return None
        return self.match_alias_supplier.nome_azienda


class PurchaseOrderReconciliationAnomaly(Base):
    __tablename__ = "purchase_order_reconciliation_anomalies"
    __table_args__ = (
        CheckConstraint("anomaly_type in ('quantity_overbilled','quantity_underbilled','unordered_item','missing_invoice_item','price_overcharge','unit_mismatch','supplier_mismatch','duplicate_invoice_line','ambiguous_match','order_not_found')", name="ck_po_reconciliation_anomalies_type"),
        CheckConstraint("workflow_status in ('da_verificare','in_parking','accettata','contestata','in_reclamo','risolta','ignorata')", name="ck_po_reconciliation_anomalies_workflow"),
        UniqueConstraint("reconciliation_id", "evidence_key", name="uq_po_reconciliation_anomaly_evidence"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reconciliation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("purchase_order_reconciliations.id", ondelete="CASCADE"), nullable=False, index=True)
    reconciliation_item_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("purchase_order_reconciliation_items.id", ondelete="CASCADE"), index=True)
    fattura_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fatture.id", ondelete="RESTRICT"), index=True)
    riga_fattura_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("righe_fattura.id", ondelete="RESTRICT"), index=True)
    liquidstock_supplier_order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    liquidstock_item_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("fornitori.id", ondelete="RESTRICT"))
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    disputed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    evidence_key: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(30), nullable=False, default="da_verificare")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    reconciliation = relationship("PurchaseOrderReconciliation", back_populates="anomalies")
