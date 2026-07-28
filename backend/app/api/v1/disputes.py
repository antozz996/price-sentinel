"""Venue-scoped APIs for disputes, communications and credit recovery."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_manager
from app.database import get_db
from app.models.anomalie import Anomalia, StatoValidazione
from app.models.disputes import (
    DisputeCase,
    DisputeCaseAnomaly,
    DisputeCommunication,
    DisputeCreditNote,
)
from app.models.fatture import Fattura, RigaFattura
from app.models.purchase_order_reconciliation import (
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
)
from app.models.utenti import Utente
from app.schemas.disputes import (
    AttachmentOut,
    CommunicationEvent,
    CommunicationOut,
    CommunicationPrepare,
    CreditNoteCreate,
    DisputeCreate,
    DisputeDashboardOut,
    DisputeOut,
    DisputeRecognition,
    DisputeTransition,
    DisputeUpdate,
    SupplierResponseCreate,
)
from app.services.dispute_pdf import generate_dispute_pdf
from app.services.disputes import (
    assert_location_access,
    create_attachment,
    create_case,
    create_credit_note,
    get_attachment,
    get_communication,
    load_case,
    prepare_communication,
    record_communication_event,
    record_supplier_response,
    set_recognition,
    transition_case,
    update_case,
)


router = APIRouter()


@router.get("/candidates")
async def list_dispute_candidates(
    location_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    source: str | None = Query(None, pattern="^(reconciliation|legacy)$"),
    limit: int = Query(100, ge=1, le=250),
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.ruolo.value != "admin":
        location_id = user.location_id
    if location_id is not None:
        assert_location_access(user, location_id)

    rows: list[dict] = []
    if source in {None, "reconciliation"}:
        statement = (
            select(
                PurchaseOrderReconciliationAnomaly,
                PurchaseOrderReconciliation,
                LiquidStockVenueMapping,
            )
            .join(
                PurchaseOrderReconciliation,
                PurchaseOrderReconciliation.id
                == PurchaseOrderReconciliationAnomaly.reconciliation_id,
            )
            .join(
                LiquidStockVenueMapping,
                LiquidStockVenueMapping.liquidstock_venue_id
                == PurchaseOrderReconciliation.venue_id,
            )
            .outerjoin(
                DisputeCaseAnomaly,
                DisputeCaseAnomaly.reconciliation_anomaly_id
                == PurchaseOrderReconciliationAnomaly.id,
            )
            .where(
                DisputeCaseAnomaly.id.is_(None),
                PurchaseOrderReconciliationAnomaly.workflow_status.notin_(
                    ["risolta", "ignorata"]
                ),
            )
        )
        if location_id is not None:
            statement = statement.where(
                LiquidStockVenueMapping.location_id == location_id
            )
        if supplier_id is not None:
            statement = statement.where(
                PurchaseOrderReconciliation.supplier_id == supplier_id
            )
        result = await db.execute(
            statement.order_by(
                PurchaseOrderReconciliationAnomaly.created_at.desc()
            ).limit(limit)
        )
        for anomaly, reconciliation, mapping in result.all():
            rows.append(
                {
                    "source": "reconciliation",
                    "id": anomaly.id,
                    "location_id": mapping.location_id,
                    "liquidstock_venue_id": str(reconciliation.venue_id),
                    "supplier_id": reconciliation.supplier_id,
                    "reconciliation_id": str(reconciliation.id),
                    "fattura_id": anomaly.fattura_id,
                    "reason": anomaly.anomaly_type,
                    "description": (
                        anomaly.evidence.get("description")
                        if anomaly.evidence
                        else None
                    ),
                    "amount": (
                        str(anomaly.disputed_amount)
                        if anomaly.disputed_amount is not None
                        else None
                    ),
                    "created_at": anomaly.created_at,
                }
            )
    if source in {None, "legacy"}:
        statement = (
            select(Anomalia, RigaFattura, Fattura)
            .join(RigaFattura, RigaFattura.id == Anomalia.riga_fattura_id)
            .join(Fattura, Fattura.id == RigaFattura.fattura_id)
            .outerjoin(
                DisputeCaseAnomaly,
                DisputeCaseAnomaly.legacy_anomaly_id == Anomalia.id,
            )
            .where(
                DisputeCaseAnomaly.id.is_(None),
                Anomalia.stato_validazione != StatoValidazione.risolta,
            )
        )
        if location_id is not None:
            statement = statement.where(Fattura.location_id == location_id)
        if supplier_id is not None:
            statement = statement.where(Fattura.fornitore_id == supplier_id)
        result = await db.execute(statement.order_by(Anomalia.id.desc()).limit(limit))
        for anomaly, line, invoice in result.all():
            rows.append(
                {
                    "source": "legacy",
                    "id": anomaly.id,
                    "location_id": invoice.location_id,
                    "liquidstock_venue_id": None,
                    "supplier_id": invoice.fornitore_id,
                    "reconciliation_id": None,
                    "fattura_id": invoice.id,
                    "reason": "price_overcharge",
                    "description": line.descrizione_fornitore_raw,
                    "amount": str(anomaly.delta_totale),
                    "created_at": invoice.data_documento,
                }
            )
    rows.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return rows[:limit]


@router.get("/dashboard", response_model=DisputeDashboardOut)
async def dispute_dashboard(
    location_id: int | None = Query(None),
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.ruolo.value != "admin":
        location_id = user.location_id
    if location_id is not None:
        assert_location_access(user, location_id)
    case_filter = (
        DisputeCase.location_id == location_id if location_id is not None else True
    )
    amounts = (
        await db.execute(
            select(
                func.count(DisputeCaseAnomaly.id),
                func.coalesce(func.sum(DisputeCaseAnomaly.claimed_amount), 0),
            )
            .join(
                DisputeCase,
                DisputeCase.id == DisputeCaseAnomaly.dispute_case_id,
            )
            .where(case_filter)
        )
    ).one()
    totals = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        DisputeCase.requested_amount
                    ).filter(
                        DisputeCase.status.notin_(["draft", "cancelled"])
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(DisputeCase.recognized_amount).filter(
                        DisputeCase.status != "cancelled"
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(DisputeCase.recovered_amount).filter(
                        DisputeCase.status != "cancelled"
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(DisputeCase.unrecovered_amount).filter(
                        DisputeCase.status != "cancelled"
                    ),
                    0,
                ),
                func.count(DisputeCase.id).filter(
                    DisputeCase.status.notin_(["closed", "cancelled"])
                ),
                func.count(DisputeCase.id).filter(
                    DisputeCase.status.notin_(["closed", "cancelled"]),
                    DisputeCase.due_date < date.today(),
                ),
                func.count(DisputeCase.id).filter(
                    DisputeCase.status.in_(
                        ["credit_note_expected", "partially_recovered"]
                    )
                ),
                func.avg(
                    func.extract(
                        "epoch", DisputeCase.updated_at - DisputeCase.created_at
                    )
                    / 86400
                ).filter(DisputeCase.status == "closed"),
            ).where(case_filter)
        )
    ).one()

    async def grouped(column, label: str):
        statement = (
            select(
                column.label("key"),
                func.count(DisputeCase.id).label("cases"),
                func.coalesce(func.sum(DisputeCase.requested_amount), 0).label(
                    "requested"
                ),
                func.coalesce(func.sum(DisputeCase.recovered_amount), 0).label(
                    "recovered"
                ),
            )
            .where(case_filter)
            .group_by(column)
            .order_by(func.sum(DisputeCase.requested_amount).desc())
        )
        return [
            {
                label: str(row.key),
                "cases": row.cases,
                "requested": str(row.requested),
                "recovered": str(row.recovered),
            }
            for row in (await db.execute(statement)).all()
        ]

    causes = (
        await db.execute(
            select(
                DisputeCaseAnomaly.reason_snapshot,
                func.count(DisputeCaseAnomaly.id),
                func.coalesce(func.sum(DisputeCaseAnomaly.claimed_amount), 0),
            )
            .join(
                DisputeCase,
                DisputeCase.id == DisputeCaseAnomaly.dispute_case_id,
            )
            .where(case_filter)
            .group_by(DisputeCaseAnomaly.reason_snapshot)
            .order_by(func.sum(DisputeCaseAnomaly.claimed_amount).desc())
        )
    ).all()
    month_bucket = func.date_trunc("month", DisputeCase.created_at)
    trend = (
        await db.execute(
            select(
                month_bucket,
                func.coalesce(func.sum(DisputeCase.requested_amount), 0),
                func.coalesce(func.sum(DisputeCase.recovered_amount), 0),
            )
            .where(case_filter)
            .group_by(month_bucket)
            .order_by(month_bucket)
        )
    ).all()
    return DisputeDashboardOut(
        total_anomalies=amounts[0],
        total_detected=amounts[1],
        total_contested=totals[0],
        total_recognized=totals[1],
        total_recovered=totals[2],
        total_outstanding=totals[3],
        open_cases=totals[4],
        overdue_cases=totals[5],
        missing_credit_notes=totals[6],
        average_resolution_days=(
            Decimal(str(totals[7])).quantize(Decimal("0.01"))
            if totals[7] is not None
            else None
        ),
        by_location=await grouped(DisputeCase.location_id, "location_id"),
        by_supplier=await grouped(DisputeCase.supplier_id, "supplier_id"),
        by_cause=[
            {
                "cause": row[0],
                "count": row[1],
                "amount": str(row[2]),
            }
            for row in causes
        ],
        monthly_trend=[
            {
                "month": row[0].date().isoformat(),
                "requested": str(row[1]),
                "recovered": str(row[2]),
            }
            for row in trend
        ],
    )


@router.get("", response_model=list[DisputeOut])
async def list_cases(
    location_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=250),
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.ruolo.value != "admin":
        location_id = user.location_id
    if location_id is not None:
        assert_location_access(user, location_id)
    statement = select(DisputeCase).options(
        selectinload(DisputeCase.anomalies),
        selectinload(DisputeCase.communications),
        selectinload(DisputeCase.attachments),
        selectinload(DisputeCase.responses),
        selectinload(DisputeCase.credit_notes).selectinload(
            DisputeCreditNote.allocations
        ),
        selectinload(DisputeCase.audit_events),
        selectinload(DisputeCase.supplier),
        selectinload(DisputeCase.location),
        selectinload(DisputeCase.owner),
    )
    if location_id is not None:
        statement = statement.where(DisputeCase.location_id == location_id)
    if supplier_id is not None:
        statement = statement.where(DisputeCase.supplier_id == supplier_id)
    if status:
        statement = statement.where(DisputeCase.status == status)
    return (
        await db.scalars(
            statement.order_by(DisputeCase.updated_at.desc()).limit(limit)
        )
    ).all()


@router.post("", response_model=DisputeOut, status_code=201)
async def create_dispute(
    payload: DisputeCreate,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    return await create_case(db, payload, actor)


@router.get("/{case_id}", response_model=DisputeOut)
async def get_case(
    case_id: UUID,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await load_case(db, case_id, user)


@router.patch("/{case_id}", response_model=DisputeOut)
async def patch_case(
    case_id: UUID,
    payload: DisputeUpdate,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await update_case(db, case, payload, actor)


@router.post("/{case_id}/transition", response_model=DisputeOut)
async def transition(
    case_id: UUID,
    payload: DisputeTransition,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await transition_case(
        db,
        case,
        payload.target_status,
        payload.expected_version,
        actor,
        payload.reason,
    )


@router.post("/{case_id}/recognition", response_model=DisputeOut)
async def recognize(
    case_id: UUID,
    payload: DisputeRecognition,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await set_recognition(db, case, payload, actor)


@router.post(
    "/{case_id}/communications",
    response_model=CommunicationOut,
    status_code=201,
)
async def create_communication(
    case_id: UUID,
    payload: CommunicationPrepare,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await prepare_communication(db, case, payload, actor)


@router.post(
    "/{case_id}/communications/{communication_id}/events",
    response_model=DisputeOut,
)
async def communication_event(
    case_id: UUID,
    communication_id: UUID,
    payload: CommunicationEvent,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    communication = await get_communication(db, communication_id)
    return await record_communication_event(
        db, case, communication, payload.action, actor
    )


@router.post("/{case_id}/responses", response_model=DisputeOut, status_code=201)
async def supplier_response(
    case_id: UUID,
    payload: SupplierResponseCreate,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await record_supplier_response(db, case, payload, actor)


@router.post(
    "/{case_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
)
async def upload_attachment(
    case_id: UUID,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    content = await file.read(10 * 1024 * 1024 + 1)
    return await create_attachment(
        db,
        case,
        actor,
        filename=file.filename or "allegato",
        content_type=file.content_type or "application/octet-stream",
        content=content,
        description=description,
    )


@router.get("/{case_id}/attachments/{attachment_id}")
async def download_attachment(
    case_id: UUID,
    attachment_id: UUID,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, user)
    attachment = await get_attachment(db, attachment_id, user)
    if attachment.dispute_case_id != case.id:
        raise HTTPException(status_code=409, detail="cross_case_attachment")
    return Response(
        content=attachment.content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{case_id}/credit-notes", response_model=DisputeOut, status_code=201)
async def register_credit_note(
    case_id: UUID,
    payload: CreditNoteCreate,
    actor: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, actor, for_update=True)
    return await create_credit_note(db, case, payload, actor)


@router.get("/{case_id}/pdf")
async def dispute_pdf(
    case_id: UUID,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = await load_case(db, case_id, user)
    content = generate_dispute_pdf(case)
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{case.case_code}.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )
