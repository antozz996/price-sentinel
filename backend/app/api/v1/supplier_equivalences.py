from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.supplier_identity_equivalence import (
    SupplierIdentityEquivalence,
    SupplierIdentityEquivalenceAudit,
)
from app.models.utenti import Utente
from app.schemas.supplier_identity_equivalence import (
    SupplierIdentityEquivalenceAuditOut,
    SupplierIdentityEquivalenceCreate,
    SupplierIdentityEquivalenceOut,
    SupplierIdentityEquivalenceUpdate,
    SupplierSearchResult,
)
from app.services.supplier_identity_equivalence import (
    SupplierEquivalenceError,
    create_equivalence,
    set_equivalence_active,
)


router = APIRouter()


def equivalence_out(
    row: SupplierIdentityEquivalence,
) -> SupplierIdentityEquivalenceOut:
    return SupplierIdentityEquivalenceOut(
        id=row.id,
        canonical_supplier_id=row.canonical_supplier_id,
        canonical_supplier_name=row.canonical_supplier.nome_azienda,
        equivalent_supplier_id=row.equivalent_supplier_id,
        equivalent_supplier_name=row.equivalent_supplier.nome_azienda,
        is_active=row.is_active,
        reason=row.reason,
        approved_by=row.approved_by,
        approved_by_email=row.approved_by_user.email,
        approved_at=row.approved_at,
        updated_by=row.updated_by,
        updated_by_email=row.updated_by_user.email,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/supplier-equivalences/search",
    response_model=list[SupplierSearchResult],
)
async def search_suppliers(
    query: str = Query(min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(require_admin),
):
    rows = (
        await db.scalars(
            select(Fornitore)
            .where(Fornitore.nome_azienda.ilike(f"%{query.strip()}%"))
            .order_by(Fornitore.nome_azienda, Fornitore.id)
            .limit(25)
        )
    ).all()
    return [SupplierSearchResult(id=row.id, name=row.nome_azienda) for row in rows]


@router.get(
    "/supplier-equivalences/audit",
    response_model=list[SupplierIdentityEquivalenceAuditOut],
)
async def equivalence_audit(
    equivalence_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(require_admin),
):
    statement = select(SupplierIdentityEquivalenceAudit)
    if equivalence_id:
        statement = statement.where(
            SupplierIdentityEquivalenceAudit.equivalence_id == equivalence_id
        )
    rows = (
        await db.scalars(
            statement.order_by(
                SupplierIdentityEquivalenceAudit.occurred_at.desc(),
                SupplierIdentityEquivalenceAudit.id.desc(),
            ).limit(250)
        )
    ).all()
    return [
        SupplierIdentityEquivalenceAuditOut(
            id=row.id,
            equivalence_id=row.equivalence_id,
            action=row.action,
            canonical_supplier_id=row.canonical_supplier_id,
            canonical_supplier_name=row.canonical_supplier.nome_azienda,
            equivalent_supplier_id=row.equivalent_supplier_id,
            equivalent_supplier_name=row.equivalent_supplier.nome_azienda,
            is_active=row.is_active,
            reason=row.reason,
            actor_id=row.actor_id,
            actor_email=row.actor.email,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]


@router.get(
    "/supplier-equivalences",
    response_model=list[SupplierIdentityEquivalenceOut],
)
async def list_equivalences(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(require_admin),
):
    statement = select(SupplierIdentityEquivalence)
    if not include_inactive:
        statement = statement.where(
            SupplierIdentityEquivalence.is_active.is_(True)
        )
    rows = (
        await db.scalars(
            statement.order_by(
                SupplierIdentityEquivalence.is_active.desc(),
                SupplierIdentityEquivalence.updated_at.desc(),
                SupplierIdentityEquivalence.id,
            )
        )
    ).all()
    return [equivalence_out(row) for row in rows]


@router.post(
    "/supplier-equivalences",
    response_model=SupplierIdentityEquivalenceOut,
)
async def add_equivalence(
    payload: SupplierIdentityEquivalenceCreate,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    if payload.confirm is not True:
        raise HTTPException(422, "supplier_equivalence_confirmation_required")
    try:
        row = await create_equivalence(
            db,
            canonical_supplier_id=payload.canonical_supplier_id,
            equivalent_supplier_id=payload.equivalent_supplier_id,
            reason=payload.reason,
            actor=user,
        )
    except SupplierEquivalenceError as error:
        raise HTTPException(error.status, error.code) from error
    await db.refresh(
        row,
        attribute_names=[
            "canonical_supplier",
            "equivalent_supplier",
            "approved_by_user",
            "updated_by_user",
        ],
    )
    return equivalence_out(row)


@router.patch(
    "/supplier-equivalences/{equivalence_id}",
    response_model=SupplierIdentityEquivalenceOut,
)
async def change_equivalence(
    equivalence_id: int,
    payload: SupplierIdentityEquivalenceUpdate,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    if payload.confirm is not True:
        raise HTTPException(422, "supplier_equivalence_confirmation_required")
    try:
        row = await set_equivalence_active(
            db,
            equivalence_id=equivalence_id,
            is_active=payload.is_active,
            reason=payload.reason,
            actor=user,
        )
    except SupplierEquivalenceError as error:
        raise HTTPException(error.status, error.code) from error
    await db.refresh(
        row,
        attribute_names=[
            "canonical_supplier",
            "equivalent_supplier",
            "approved_by_user",
            "updated_by_user",
        ],
    )
    return equivalence_out(row)
