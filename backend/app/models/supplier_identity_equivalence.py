"""Explicit, auditable supplier identity equivalences."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SupplierIdentityEquivalence(Base):
    __tablename__ = "supplier_identity_equivalences"
    __table_args__ = (
        CheckConstraint(
            "canonical_supplier_id <> equivalent_supplier_id",
            name="ck_supplier_identity_equivalences_distinct",
        ),
        CheckConstraint(
            "length(btrim(reason)) >= 8",
            name="ck_supplier_identity_equivalences_reason",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    canonical_supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    equivalent_supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    canonical_supplier = relationship(
        "Fornitore", foreign_keys=[canonical_supplier_id], lazy="selectin"
    )
    equivalent_supplier = relationship(
        "Fornitore", foreign_keys=[equivalent_supplier_id], lazy="selectin"
    )
    approved_by_user = relationship(
        "Utente", foreign_keys=[approved_by], lazy="selectin"
    )
    updated_by_user = relationship(
        "Utente", foreign_keys=[updated_by], lazy="selectin"
    )
    audit_entries = relationship(
        "SupplierIdentityEquivalenceAudit",
        back_populates="equivalence",
        lazy="selectin",
    )


class SupplierIdentityEquivalenceAudit(Base):
    __tablename__ = "supplier_identity_equivalence_audit"
    __table_args__ = (
        CheckConstraint(
            "action in ('created','activated','deactivated','updated')",
            name="ck_supplier_identity_equivalence_audit_action",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    equivalence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("supplier_identity_equivalences.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
    )
    equivalent_supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fornitori.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("utenti.id", ondelete="RESTRICT"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    equivalence = relationship(
        "SupplierIdentityEquivalence", back_populates="audit_entries"
    )
    canonical_supplier = relationship(
        "Fornitore", foreign_keys=[canonical_supplier_id], lazy="selectin"
    )
    equivalent_supplier = relationship(
        "Fornitore", foreign_keys=[equivalent_supplier_id], lazy="selectin"
    )
    actor = relationship("Utente", foreign_keys=[actor_id], lazy="selectin")
