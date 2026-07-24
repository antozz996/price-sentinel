from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura
from app.models.liquidstock_integration import LiquidStockSupplierOrder, LiquidStockSupplierOrderItem
from app.models.location import Location
from app.models.products import Product
from app.models.purchase_order_reconciliation import LiquidStockVenueMapping, PurchaseOrderReconciliation, PurchaseOrderReconciliationItem
from app.models.utenti import Utente
from app.schemas.purchase_order_reconciliation import AttachInvoiceInput, CloseReconciliationInput, InvoiceCandidateOut, OrderCandidateOut, ReconciliationAnomalyOut, ReconciliationDetailOut, ReconciliationItemOut, ResolveItemInput, VenueMappingInput
from app.services.purchase_order_reconciliation import ReconciliationError, attach_invoice, confirm_candidate, create_anomaly, detach_invoice, ensure_reconciliation, run_matching

router = APIRouter()


async def mapping(db: AsyncSession, venue_id: UUID):
    return await db.scalar(select(LiquidStockVenueMapping).where(LiquidStockVenueMapping.liquidstock_venue_id == venue_id))


async def authorize(db: AsyncSession, user: Utente, venue_id: UUID):
    found = await mapping(db, venue_id)
    if user.ruolo.value != "admin" and (not found or user.location_id != found.location_id):
        raise HTTPException(403, "cross_venue_forbidden")
    return found


async def load(db: AsyncSession, rid: UUID, user: Utente):
    row = await db.get(PurchaseOrderReconciliation, rid)
    if not row: raise HTTPException(404, "reconciliation_not_found")
    await authorize(db, user, row.venue_id)
    return row


async def detail(db: AsyncSession, row: PurchaseOrderReconciliation):
    await db.refresh(row, attribute_names=["items", "anomalies", "invoice", "supplier"])
    venue_map = await mapping(db, row.venue_id)
    location = await db.get(Location, venue_map.location_id) if venue_map else None
    return ReconciliationDetailOut(
        id=row.id, liquidstock_supplier_order_id=row.liquidstock_supplier_order_id,
        liquidstock_order_id=row.liquidstock_order_id, supplier_id=row.supplier_id,
        fattura_id=row.fattura_id, venue_id=row.venue_id, status=row.status,
        matching_confidence=row.matching_confidence, reconciliation_version=row.reconciliation_version,
        price_tolerance_absolute=row.price_tolerance_absolute, price_tolerance_percent=row.price_tolerance_percent,
        started_at=row.started_at, completed_at=row.completed_at, created_at=row.created_at, updated_at=row.updated_at,
        invoice_number=row.invoice.numero_documento if row.invoice else None,
        invoice_date=row.invoice.data_documento if row.invoice else None,
        supplier_name=row.supplier.nome_azienda if row.supplier else None,
        venue_name=location.nome_struttura if location else None,
        items=[ReconciliationItemOut.model_validate(item) for item in row.items],
        anomalies=[ReconciliationAnomalyOut.model_validate(item) for item in row.anomalies],
    )


@router.get("/venue-mappings")
async def mappings(db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    rows = (await db.execute(select(LiquidStockVenueMapping, Location).join(Location).order_by(Location.nome_struttura))).all()
    if user.ruolo.value != "admin": rows = [r for r in rows if r.LiquidStockVenueMapping.location_id == user.location_id]
    return [{"liquidstock_venue_id": r.LiquidStockVenueMapping.liquidstock_venue_id, "venue_name_snapshot": r.LiquidStockVenueMapping.venue_name_snapshot, "location_id": r.Location.id, "location_name": r.Location.nome_struttura} for r in rows]


@router.post("/venue-mappings")
async def save_mapping(payload: VenueMappingInput, db: AsyncSession = Depends(get_db), _: Utente = Depends(require_admin)):
    order = await db.scalar(select(LiquidStockSupplierOrder).where(LiquidStockSupplierOrder.liquidstock_venue_id == payload.liquidstock_venue_id).limit(1))
    location = await db.get(Location, payload.location_id)
    if not order or not location: raise HTTPException(404, "venue_or_location_not_found")
    conflict = await db.scalar(select(LiquidStockVenueMapping).where(LiquidStockVenueMapping.location_id == payload.location_id, LiquidStockVenueMapping.liquidstock_venue_id != payload.liquidstock_venue_id))
    if conflict: raise HTTPException(409, "location_already_mapped")
    row = await mapping(db, payload.liquidstock_venue_id); now = datetime.now(timezone.utc)
    if row: row.location_id = payload.location_id; row.venue_name_snapshot = order.venue_name_snapshot; row.updated_at = now
    else: row = LiquidStockVenueMapping(liquidstock_venue_id=payload.liquidstock_venue_id, location_id=payload.location_id, venue_name_snapshot=order.venue_name_snapshot, created_at=now, updated_at=now); db.add(row)
    await db.flush(); return {"saved": True, "liquidstock_venue_id": row.liquidstock_venue_id, "location_id": row.location_id}


@router.get("/orders", response_model=list[OrderCandidateOut])
async def orders(venue_id: UUID | None = None, supplier_id: int | None = Query(default=None, gt=0), status: str | None = None, date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    stmt = select(LiquidStockSupplierOrder, PurchaseOrderReconciliation).outerjoin(PurchaseOrderReconciliation, PurchaseOrderReconciliation.liquidstock_supplier_order_id == LiquidStockSupplierOrder.liquidstock_supplier_order_id)
    if venue_id: stmt = stmt.where(LiquidStockSupplierOrder.liquidstock_venue_id == venue_id)
    if supplier_id: stmt = stmt.where(LiquidStockSupplierOrder.supplier_id == supplier_id)
    if status: stmt = stmt.where(or_(PurchaseOrderReconciliation.status == status, LiquidStockSupplierOrder.status == status))
    if date_from: stmt = stmt.where(LiquidStockSupplierOrder.sent_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to: stmt = stmt.where(LiquidStockSupplierOrder.sent_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc))
    output = []
    for order, reconciliation in (await db.execute(stmt.order_by(LiquidStockSupplierOrder.updated_at.desc()).limit(250))).all():
        try: await authorize(db, user, order.liquidstock_venue_id)
        except HTTPException: continue
        output.append(OrderCandidateOut(liquidstock_supplier_order_id=order.liquidstock_supplier_order_id, liquidstock_order_id=order.liquidstock_order_id, liquidstock_venue_id=order.liquidstock_venue_id, venue_name_snapshot=order.venue_name_snapshot, supplier_id=order.supplier_id, supplier_name_snapshot=order.supplier_name_snapshot, status=order.status, sent_at=order.sent_at, requested_delivery_date=order.requested_delivery_date, received_at=order.received_at, reconciliation_id=reconciliation.id if reconciliation else None, reconciliation_status=reconciliation.status if reconciliation else None, fattura_id=reconciliation.fattura_id if reconciliation else None))
    return output


@router.get("/{rid}", response_model=ReconciliationDetailOut)
async def get_one(rid: UUID, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    return await detail(db, await load(db, rid, user))


@router.get("/orders/{supplier_order_id}/invoice-candidates", response_model=list[InvoiceCandidateOut])
async def candidates(supplier_order_id: UUID, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    order = await db.scalar(select(LiquidStockSupplierOrder).where(LiquidStockSupplierOrder.liquidstock_supplier_order_id == supplier_order_id))
    if not order: raise HTTPException(404, "order_not_found")
    venue_map = await authorize(db, user, order.liquidstock_venue_id)
    if not venue_map: raise HTTPException(409, "venue_mapping_required")
    if order.supplier_id is None: raise HTTPException(409, "supplier_mapping_required")
    invoices = (await db.scalars(select(Fattura).where(Fattura.fornitore_id == order.supplier_id, Fattura.location_id == venue_map.location_id).order_by(Fattura.data_documento.desc()).limit(100))).all()
    order_products = set((await db.scalars(select(LiquidStockSupplierOrderItem.product_id).where(LiquidStockSupplierOrderItem.supplier_order_id == order.id, LiquidStockSupplierOrderItem.product_id.is_not(None)))).all())
    product_skus = set((await db.scalars(select(Product.sku_interno).where(Product.id.in_(order_products)))).all()) if order_products else set()
    result = []
    for invoice in invoices:
        associated = await db.scalar(select(PurchaseOrderReconciliation.id).where(PurchaseOrderReconciliation.fattura_id == invoice.id))
        invoice_skus = set((await db.scalars(select(RigaFattura.sku_interno).where(RigaFattura.fattura_id == invoice.id, RigaFattura.sku_interno.is_not(None)))).all())
        overlap = len(invoice_skus & product_skus); reference = order.received_at.date() if order.received_at else (order.requested_delivery_date or (order.sent_at.date() if order.sent_at else invoice.data_documento)); days = abs((invoice.data_documento-reference).days)
        score = Decimal("0.5") + (Decimal("0.3") if days <= 14 else 0) + min(Decimal("0.2"), Decimal(overlap)*Decimal("0.05"))
        reasons = ["fornitore esplicito", "venue/location esplicita", f"distanza data {days} giorni"] + ([f"{overlap} prodotti canonici in comune"] if overlap else [])
        result.append(InvoiceCandidateOut(id=invoice.id, fornitore_id=invoice.fornitore_id, location_id=invoice.location_id, numero_documento=invoice.numero_documento, data_documento=invoice.data_documento, totale_imponibile=invoice.totale_imponibile, already_associated_to=associated, suggestion_score=score, suggestion_reasons=reasons))
    return result


@router.post("/orders/{supplier_order_id}/invoice", response_model=ReconciliationDetailOut)
async def associate(supplier_order_id: UUID, payload: AttachInvoiceInput, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    order = await db.scalar(select(LiquidStockSupplierOrder).where(LiquidStockSupplierOrder.liquidstock_supplier_order_id == supplier_order_id).with_for_update())
    if not order: raise HTTPException(404, "order_not_found")
    await authorize(db, user, order.liquidstock_venue_id); invoice = await db.get(Fattura, payload.fattura_id)
    if not invoice: raise HTTPException(404, "invoice_not_found")
    row = await ensure_reconciliation(db, order)
    try: await attach_invoice(db, row, invoice, allow_reassociate=payload.allow_reassociate, tolerance_absolute=payload.price_tolerance_absolute, tolerance_percent=payload.price_tolerance_percent)
    except ReconciliationError as error: raise HTTPException(error.status, error.code)
    return await detail(db, row)


@router.delete("/{rid}/invoice", response_model=ReconciliationDetailOut)
async def unlink(rid: UUID, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    row = await load(db, rid, user)
    try: await detach_invoice(db, row)
    except ReconciliationError as error: raise HTTPException(error.status, error.code)
    await db.flush(); return await detail(db, row)


@router.post("/{rid}/match", response_model=ReconciliationDetailOut)
async def match(rid: UUID, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    row = await load(db, rid, user)
    try: await run_matching(db, row)
    except ReconciliationError as error: raise HTTPException(error.status, error.code)
    return await detail(db, row)


@router.post("/{rid}/items/{item_id}/resolve", response_model=ReconciliationDetailOut)
async def resolve(rid: UUID, item_id: int, payload: ResolveItemInput, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    row = await load(db, rid, user)
    if row.status == "closed": raise HTTPException(409, "closed_reconciliation_is_immutable")
    item = await db.scalar(select(PurchaseOrderReconciliationItem).where(PurchaseOrderReconciliationItem.id == item_id, PurchaseOrderReconciliationItem.reconciliation_id == row.id))
    if not item: raise HTTPException(404, "reconciliation_item_not_found")
    if payload.action == "ignore": item.match_status = "ignored"; item.anomaly_type = None; item.notes = payload.notes
    elif payload.action == "create_anomaly":
        try: await create_anomaly(db, row, item, payload.notes)
        except ReconciliationError as error: raise HTTPException(error.status, error.code)
    else:
        if not payload.liquidstock_item_id or not payload.product_id: raise HTTPException(422, "confirmed_match_requires_targets")
        order = await db.scalar(select(LiquidStockSupplierOrder).where(LiquidStockSupplierOrder.liquidstock_supplier_order_id == row.liquidstock_supplier_order_id))
        target = await db.scalar(select(LiquidStockSupplierOrderItem).where(LiquidStockSupplierOrderItem.supplier_order_id == order.id, LiquidStockSupplierOrderItem.liquidstock_supplier_order_item_id == payload.liquidstock_item_id, LiquidStockSupplierOrderItem.product_id == payload.product_id))
        if not target: raise HTTPException(409, "confirmed_match_target_invalid")
        try: await confirm_candidate(db, row, item, target, payload.notes)
        except ReconciliationError as error: raise HTTPException(error.status, error.code)
    row.status="reviewed"; row.reconciliation_version += 1; row.updated_at=datetime.now(timezone.utc); await db.flush(); return await detail(db,row)


@router.post("/{rid}/close", response_model=ReconciliationDetailOut)
async def close(rid: UUID, _: CloseReconciliationInput, db: AsyncSession = Depends(get_db), user: Utente = Depends(get_current_user)):
    row = await load(db,rid,user); unresolved = await db.scalar(select(PurchaseOrderReconciliationItem.id).where(PurchaseOrderReconciliationItem.reconciliation_id==row.id, PurchaseOrderReconciliationItem.match_status=="ambiguous").limit(1))
    if unresolved: raise HTTPException(409,"ambiguous_items_require_review")
    row.status="closed"; row.completed_at=datetime.now(timezone.utc); row.updated_at=row.completed_at; row.reconciliation_version += 1; await db.flush(); return await detail(db,row)
