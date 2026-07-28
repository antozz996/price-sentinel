"""Business rules for explicit supplier identity equivalences."""

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fornitori import Fornitore
from app.models.purchase_order_reconciliation import PurchaseOrderReconciliation
from app.models.supplier_identity_equivalence import SupplierIdentityEquivalence
from app.models.utenti import Utente


class SupplierEquivalenceError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


async def active_equivalence_for_pair(
    db: AsyncSession,
    first_supplier_id: int,
    second_supplier_id: int,
) -> SupplierIdentityEquivalence | None:
    if first_supplier_id == second_supplier_id:
        return None
    return await db.scalar(
        select(SupplierIdentityEquivalence).where(
            SupplierIdentityEquivalence.is_active.is_(True),
            or_(
                (
                    SupplierIdentityEquivalence.canonical_supplier_id
                    == first_supplier_id
                )
                & (
                    SupplierIdentityEquivalence.equivalent_supplier_id
                    == second_supplier_id
                ),
                (
                    SupplierIdentityEquivalence.canonical_supplier_id
                    == second_supplier_id
                )
                & (
                    SupplierIdentityEquivalence.equivalent_supplier_id
                    == first_supplier_id
                ),
            ),
        )
    )


async def supplier_scope(
    db: AsyncSession, supplier_id: int
) -> tuple[list[int], SupplierIdentityEquivalence | None]:
    equivalence = await db.scalar(
        select(SupplierIdentityEquivalence).where(
            SupplierIdentityEquivalence.is_active.is_(True),
            or_(
                SupplierIdentityEquivalence.canonical_supplier_id == supplier_id,
                SupplierIdentityEquivalence.equivalent_supplier_id == supplier_id,
            ),
        )
    )
    if not equivalence:
        return [supplier_id], None
    counterpart = (
        equivalence.equivalent_supplier_id
        if equivalence.canonical_supplier_id == supplier_id
        else equivalence.canonical_supplier_id
    )
    return [supplier_id, counterpart], equivalence


async def create_equivalence(
    db: AsyncSession,
    *,
    canonical_supplier_id: int,
    equivalent_supplier_id: int,
    reason: str,
    actor: Utente,
) -> SupplierIdentityEquivalence:
    if canonical_supplier_id == equivalent_supplier_id:
        raise SupplierEquivalenceError("supplier_equivalence_self_forbidden", 422)
    suppliers = set(
        (
            await db.scalars(
                select(Fornitore.id).where(
                    Fornitore.id.in_(
                        [canonical_supplier_id, equivalent_supplier_id]
                    )
                )
            )
        ).all()
    )
    if suppliers != {canonical_supplier_id, equivalent_supplier_id}:
        raise SupplierEquivalenceError("supplier_equivalence_supplier_not_found", 404)

    existing = await db.scalar(
        select(SupplierIdentityEquivalence).where(
            or_(
                (
                    SupplierIdentityEquivalence.canonical_supplier_id
                    == canonical_supplier_id
                )
                & (
                    SupplierIdentityEquivalence.equivalent_supplier_id
                    == equivalent_supplier_id
                ),
                (
                    SupplierIdentityEquivalence.canonical_supplier_id
                    == equivalent_supplier_id
                )
                & (
                    SupplierIdentityEquivalence.equivalent_supplier_id
                    == canonical_supplier_id
                ),
            )
        )
    )
    if existing:
        code = (
            "supplier_equivalence_duplicate"
            if existing.is_active
            else "supplier_equivalence_pair_inactive"
        )
        raise SupplierEquivalenceError(code)

    overlap = await db.scalar(
        select(SupplierIdentityEquivalence.id).where(
            SupplierIdentityEquivalence.is_active.is_(True),
            or_(
                SupplierIdentityEquivalence.canonical_supplier_id.in_(
                    [canonical_supplier_id, equivalent_supplier_id]
                ),
                SupplierIdentityEquivalence.equivalent_supplier_id.in_(
                    [canonical_supplier_id, equivalent_supplier_id]
                ),
            ),
        )
    )
    if overlap:
        raise SupplierEquivalenceError(
            "supplier_equivalence_transitive_or_cycle_forbidden"
        )

    now = datetime.now(timezone.utc)
    row = SupplierIdentityEquivalence(
        canonical_supplier_id=canonical_supplier_id,
        equivalent_supplier_id=equivalent_supplier_id,
        is_active=True,
        reason=reason.strip(),
        approved_by=actor.id,
        approved_at=now,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as error:
        raise SupplierEquivalenceError(
            "supplier_equivalence_conflict"
        ) from error
    return row


async def set_equivalence_active(
    db: AsyncSession,
    *,
    equivalence_id: int,
    is_active: bool,
    reason: str,
    actor: Utente,
) -> SupplierIdentityEquivalence:
    row = await db.scalar(
        select(SupplierIdentityEquivalence)
        .where(SupplierIdentityEquivalence.id == equivalence_id)
        .with_for_update()
    )
    if not row:
        raise SupplierEquivalenceError("supplier_equivalence_not_found", 404)
    if row.is_active == is_active:
        raise SupplierEquivalenceError("supplier_equivalence_state_unchanged")
    if not is_active:
        operational = await db.scalar(
            select(PurchaseOrderReconciliation.id)
            .where(
                PurchaseOrderReconciliation.supplier_equivalence_id == row.id,
                PurchaseOrderReconciliation.fattura_id.is_not(None),
                PurchaseOrderReconciliation.status != "closed",
            )
            .limit(1)
        )
        if operational:
            raise SupplierEquivalenceError(
                "supplier_equivalence_in_use_by_open_reconciliation"
            )

    now = datetime.now(timezone.utc)
    row.is_active = is_active
    row.reason = reason.strip()
    row.updated_by = actor.id
    row.updated_at = now
    if is_active:
        row.approved_by = actor.id
        row.approved_at = now
    try:
        await db.flush()
    except IntegrityError as error:
        raise SupplierEquivalenceError(
            "supplier_equivalence_conflict"
        ) from error
    return row
