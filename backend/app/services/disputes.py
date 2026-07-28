"""Transactional business rules for supplier disputes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.anomalie import Anomalia, StatoValidazione
from app.models.disputes import (
    DisputeAttachment,
    DisputeAuditEvent,
    DisputeCase,
    DisputeCaseAnomaly,
    DisputeCommunication,
    DisputeCreditNote,
    DisputeCreditNoteAllocation,
    DisputeSupplierResponse,
)
from app.models.fatture import Fattura, RigaFattura, TipoDocumento
from app.models.purchase_order_reconciliation import (
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
)
from app.models.utenti import Utente
from app.schemas.disputes import (
    CommunicationPrepare,
    CreditNoteCreate,
    DisputeCreate,
    DisputeRecognition,
    DisputeUpdate,
    SupplierResponseCreate,
)


ZERO = Decimal("0")
TERMINAL_CASE_STATUSES = {"closed", "cancelled"}
CASE_TRANSITIONS = {
    "draft": {"ready_to_send", "cancelled"},
    "ready_to_send": {"sent", "cancelled"},
    "sent": {"supplier_replied", "credit_note_expected", "rejected", "cancelled"},
    "supplier_replied": {
        "credit_note_expected",
        "partially_recovered",
        "recovered",
        "rejected",
        "closed",
    },
    "credit_note_expected": {
        "partially_recovered",
        "recovered",
        "rejected",
        "closed",
    },
    "partially_recovered": {"recovered", "closed"},
    "recovered": {"closed"},
    "rejected": {"closed"},
    "closed": set(),
    "cancelled": set(),
}
COMMUNICATION_ACTIONS = {
    "copied": ("copied", "copied_at", 1),
    "opened": ("opened", "opened_at", 2),
    "sent_manual": ("sent_manual", "sent_manual_at", 3),
    "confirmed": ("confirmed", "confirmed_at", 4),
    "response_received": ("response_received", "response_received_at", 5),
}
COMMUNICATION_RANK = {
    "prepared": 0,
    "copied": 1,
    "opened": 2,
    "sent_manual": 3,
    "confirmed": 4,
    "response_received": 5,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: Decimal | int | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


def _case_state(case: DisputeCase) -> dict:
    return {
        "status": case.status,
        "version": case.version,
        "owner_user_id": case.owner_user_id,
        "due_date": case.due_date.isoformat() if case.due_date else None,
        "requested_amount": str(case.requested_amount),
        "recognized_amount": str(case.recognized_amount),
        "recovered_amount": str(case.recovered_amount),
        "unrecovered_amount": str(case.unrecovered_amount),
    }


def assert_location_access(user: Utente, location_id: int) -> None:
    if user.ruolo.value == "admin":
        return
    if user.location_id != location_id:
        raise HTTPException(status_code=403, detail="dispute_location_forbidden")


async def _audit(
    db: AsyncSession,
    case: DisputeCase,
    actor: Utente,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        DisputeAuditEvent(
            dispute_case_id=case.id,
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before,
            after_state=after,
            event_metadata=metadata,
            created_at=_now(),
        )
    )


def _case_options():
    return (
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


async def load_case(
    db: AsyncSession,
    case_id: UUID,
    user: Utente,
    *,
    for_update: bool = False,
) -> DisputeCase:
    statement = (
        select(DisputeCase)
        .options(*_case_options())
        .where(DisputeCase.id == case_id)
    )
    if for_update:
        statement = statement.with_for_update()
    case = await db.scalar(statement)
    if not case:
        raise HTTPException(status_code=404, detail="dispute_case_not_found")
    assert_location_access(user, case.location_id)
    return case


async def refresh_case(
    db: AsyncSession, case_id: UUID, user: Utente
) -> DisputeCase:
    await db.flush()
    statement = (
        select(DisputeCase)
        .execution_options(populate_existing=True)
        .options(*_case_options())
        .where(DisputeCase.id == case_id)
    )
    case = await db.scalar(statement)
    if not case:
        raise HTTPException(status_code=404, detail="dispute_case_not_found")
    assert_location_access(user, case.location_id)
    return case


async def _validate_owner(
    db: AsyncSession, owner_user_id: int | None, location_id: int
) -> None:
    if owner_user_id is None:
        return
    owner = await db.get(Utente, owner_user_id)
    if not owner or not owner.attivo:
        raise HTTPException(status_code=422, detail="dispute_owner_invalid")
    if owner.ruolo.value != "admin" and owner.location_id != location_id:
        raise HTTPException(status_code=422, detail="dispute_owner_cross_location")


async def _resolve_reconciliation_selection(
    db: AsyncSession, selection
) -> dict:
    row = (
        await db.execute(
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
            .where(
                PurchaseOrderReconciliationAnomaly.id
                == selection.reconciliation_anomaly_id
            )
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="reconciliation_anomaly_not_found")
    anomaly, reconciliation, mapping = row
    if anomaly.workflow_status in {"risolta", "ignorata"}:
        raise HTTPException(status_code=409, detail="anomaly_not_disputable")
    if reconciliation.supplier_id is None:
        raise HTTPException(status_code=409, detail="anomaly_supplier_missing")
    claimed = _money(selection.claimed_amount or anomaly.disputed_amount)
    if claimed <= ZERO:
        raise HTTPException(
            status_code=422, detail="positive_claimed_amount_required"
        )
    reason = (selection.reason or anomaly.anomaly_type).strip()
    return {
        "source_family": "reconciliation",
        "location_id": mapping.location_id,
        "venue_id": reconciliation.venue_id,
        "supplier_id": reconciliation.supplier_id,
        "reconciliation_id": reconciliation.id,
        "reconciliation_anomaly_id": anomaly.id,
        "legacy_anomaly_id": None,
        "claimed": claimed,
        "reason": reason,
        "evidence": {
            "source": "purchase_order_reconciliation",
            "anomaly_type": anomaly.anomaly_type,
            "fattura_id": anomaly.fattura_id,
            "riga_fattura_id": anomaly.riga_fattura_id,
            "liquidstock_supplier_order_id": str(
                anomaly.liquidstock_supplier_order_id
            ),
            "liquidstock_item_id": (
                str(anomaly.liquidstock_item_id)
                if anomaly.liquidstock_item_id
                else None
            ),
            "evidence": anomaly.evidence,
        },
    }


async def _resolve_legacy_selection(db: AsyncSession, selection) -> dict:
    row = (
        await db.execute(
            select(Anomalia, RigaFattura, Fattura)
            .join(RigaFattura, RigaFattura.id == Anomalia.riga_fattura_id)
            .join(Fattura, Fattura.id == RigaFattura.fattura_id)
            .where(Anomalia.id == selection.legacy_anomaly_id)
        )
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="legacy_anomaly_not_found")
    anomaly, line, invoice = row
    if anomaly.stato_validazione == StatoValidazione.risolta:
        raise HTTPException(status_code=409, detail="anomaly_not_disputable")
    claimed = _money(selection.claimed_amount or anomaly.delta_totale)
    if claimed <= ZERO:
        raise HTTPException(
            status_code=422, detail="positive_claimed_amount_required"
        )
    reason = (selection.reason or "price_overcharge").strip()
    return {
        "source_family": "legacy",
        "location_id": invoice.location_id,
        "venue_id": None,
        "supplier_id": invoice.fornitore_id,
        "reconciliation_id": None,
        "reconciliation_anomaly_id": None,
        "legacy_anomaly_id": anomaly.id,
        "claimed": claimed,
        "reason": reason,
        "evidence": {
            "source": "legacy_anomaly",
            "fattura_id": invoice.id,
            "invoice_number": invoice.numero_documento,
            "invoice_date": invoice.data_documento.isoformat(),
            "riga_fattura_id": line.id,
            "description": line.descrizione_fornitore_raw,
            "quantity": str(line.quantita),
            "expected_unit_price": str(anomaly.prezzo_listino_snapshot),
            "invoiced_unit_price": str(anomaly.prezzo_fatturato_snapshot),
        },
    }


async def create_case(
    db: AsyncSession, payload: DisputeCreate, actor: Utente
) -> DisputeCase:
    resolved = []
    for selection in payload.anomalies:
        if selection.reconciliation_anomaly_id is not None:
            resolved.append(
                await _resolve_reconciliation_selection(db, selection)
            )
        else:
            resolved.append(await _resolve_legacy_selection(db, selection))

    first = resolved[0]
    if any(
        item["location_id"] != first["location_id"]
        or item["supplier_id"] != first["supplier_id"]
        or item["source_family"] != first["source_family"]
        or item["reconciliation_id"] != first["reconciliation_id"]
        for item in resolved
    ):
        raise HTTPException(
            status_code=409, detail="dispute_sources_must_share_context"
        )
    assert_location_access(actor, first["location_id"])
    await _validate_owner(db, payload.owner_user_id, first["location_id"])

    reconciliation_ids = [
        item["reconciliation_anomaly_id"]
        for item in resolved
        if item["reconciliation_anomaly_id"] is not None
    ]
    legacy_ids = [
        item["legacy_anomaly_id"]
        for item in resolved
        if item["legacy_anomaly_id"] is not None
    ]
    duplicate = await db.scalar(
        select(func.count(DisputeCaseAnomaly.id)).where(
            (
                DisputeCaseAnomaly.reconciliation_anomaly_id.in_(
                    reconciliation_ids or [-1]
                )
            )
            | (DisputeCaseAnomaly.legacy_anomaly_id.in_(legacy_ids or [-1]))
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="anomaly_already_disputed")

    now = _now()
    requested = sum((item["claimed"] for item in resolved), ZERO)
    case_id = uuid4()
    case = DisputeCase(
        id=case_id,
        case_code=f"DSP-{now:%Y%m%d}-{case_id.hex[:8].upper()}",
        location_id=first["location_id"],
        liquidstock_venue_id=first["venue_id"],
        supplier_id=first["supplier_id"],
        reconciliation_id=first["reconciliation_id"],
        status="draft",
        title=payload.title.strip(),
        owner_user_id=payload.owner_user_id,
        due_date=payload.due_date,
        internal_notes=payload.internal_notes,
        requested_amount=requested,
        recognized_amount=ZERO,
        recovered_amount=ZERO,
        unrecovered_amount=requested,
        version=1,
        created_by=actor.id,
        updated_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    for item in resolved:
        db.add(
            DisputeCaseAnomaly(
                dispute_case_id=case.id,
                reconciliation_anomaly_id=item["reconciliation_anomaly_id"],
                legacy_anomaly_id=item["legacy_anomaly_id"],
                claimed_amount=item["claimed"],
                recognized_amount=ZERO,
                recovered_amount=ZERO,
                reason_snapshot=item["reason"],
                evidence_snapshot=item["evidence"],
                created_at=now,
            )
        )
    await db.flush()
    await _audit(
        db,
        case,
        actor,
        "case_created",
        "dispute_case",
        str(case.id),
        after=_case_state(case),
        metadata={"anomaly_count": len(resolved)},
    )
    return await refresh_case(db, case.id, actor)


async def update_case(
    db: AsyncSession, case: DisputeCase, payload: DisputeUpdate, actor: Utente
) -> DisputeCase:
    if case.status in TERMINAL_CASE_STATUSES:
        raise HTTPException(status_code=409, detail="terminal_case_immutable")
    if case.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="dispute_version_conflict")
    before = _case_state(case)
    if payload.title is not None:
        case.title = payload.title.strip()
    if "owner_user_id" in payload.model_fields_set:
        await _validate_owner(db, payload.owner_user_id, case.location_id)
        case.owner_user_id = payload.owner_user_id
    if "due_date" in payload.model_fields_set:
        case.due_date = payload.due_date
    if "internal_notes" in payload.model_fields_set:
        case.internal_notes = payload.internal_notes
    case.version += 1
    case.updated_by = actor.id
    case.updated_at = _now()
    await _audit(
        db,
        case,
        actor,
        "case_updated",
        "dispute_case",
        str(case.id),
        before=before,
        after=_case_state(case),
    )
    return await refresh_case(db, case.id, actor)


async def transition_case(
    db: AsyncSession,
    case: DisputeCase,
    target_status: str,
    expected_version: int,
    actor: Utente,
    reason: str | None = None,
) -> DisputeCase:
    if case.version != expected_version:
        raise HTTPException(status_code=409, detail="dispute_version_conflict")
    if target_status not in CASE_TRANSITIONS.get(case.status, set()):
        raise HTTPException(status_code=409, detail="dispute_transition_forbidden")
    if target_status in TERMINAL_CASE_STATUSES and len((reason or "").strip()) < 8:
        raise HTTPException(status_code=422, detail="terminal_reason_required")
    if target_status == "ready_to_send" and not case.anomalies:
        raise HTTPException(status_code=409, detail="dispute_has_no_anomalies")
    if target_status == "sent" and not any(
        message.status in {"confirmed", "response_received"}
        for message in case.communications
    ):
        raise HTTPException(
            status_code=409, detail="confirmed_communication_required"
        )
    if target_status == "recovered" and case.recovered_amount != case.requested_amount:
        raise HTTPException(status_code=409, detail="dispute_not_fully_recovered")
    before = _case_state(case)
    case.status = target_status
    if target_status in TERMINAL_CASE_STATUSES:
        case.manual_close_reason = reason.strip()
    case.version += 1
    case.updated_by = actor.id
    case.updated_at = _now()
    if target_status == "sent":
        await mark_source_anomalies_in_dispute(db, case, actor)
    await _audit(
        db,
        case,
        actor,
        "case_status_changed",
        "dispute_case",
        str(case.id),
        before=before,
        after=_case_state(case),
        metadata={"reason": reason},
    )
    return await refresh_case(db, case.id, actor)


async def mark_source_anomalies_in_dispute(
    db: AsyncSession, case: DisputeCase, actor: Utente
) -> None:
    """Escalate source anomalies only after an operator confirms the send."""
    reconciliation_ids = [
        row.reconciliation_anomaly_id
        for row in case.anomalies
        if row.reconciliation_anomaly_id
    ]
    legacy_ids = [
        row.legacy_anomaly_id for row in case.anomalies if row.legacy_anomaly_id
    ]
    if reconciliation_ids:
        anomalies = (
            await db.scalars(
                select(PurchaseOrderReconciliationAnomaly).where(
                    PurchaseOrderReconciliationAnomaly.id.in_(
                        reconciliation_ids
                    )
                )
            )
        ).all()
        for anomaly in anomalies:
            anomaly.workflow_status = "in_reclamo"
            anomaly.updated_at = _now()
    if legacy_ids:
        anomalies = (
            await db.scalars(
                select(Anomalia).where(Anomalia.id.in_(legacy_ids))
            )
        ).all()
        for anomaly in anomalies:
            anomaly.stato_validazione = StatoValidazione.in_reclamo
            anomaly.gestito_da_admin_id = (
                actor.id if actor.ruolo.value == "admin" else None
            )
            anomaly.gestito_at = _now()


async def set_recognition(
    db: AsyncSession,
    case: DisputeCase,
    payload: DisputeRecognition,
    actor: Utente,
) -> DisputeCase:
    if case.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="dispute_version_conflict")
    if case.status not in {
        "sent",
        "supplier_replied",
        "credit_note_expected",
        "partially_recovered",
    }:
        raise HTTPException(status_code=409, detail="recognition_not_allowed")
    rows = {row.id: row for row in case.anomalies}
    if len({item.case_anomaly_id for item in payload.allocations}) != len(
        payload.allocations
    ):
        raise HTTPException(status_code=422, detail="duplicate_recognition_item")
    before = _case_state(case)
    for item in payload.allocations:
        row = rows.get(item.case_anomaly_id)
        if not row:
            raise HTTPException(status_code=409, detail="cross_case_allocation")
        amount = _money(item.amount)
        if amount < _money(row.recovered_amount) or amount > _money(
            row.claimed_amount
        ):
            raise HTTPException(status_code=422, detail="recognized_amount_invalid")
        row.recognized_amount = amount
    await recompute_case_amounts(case)
    case.status = (
        "partially_recovered"
        if case.recovered_amount > ZERO
        else "credit_note_expected"
    )
    case.version += 1
    case.updated_by = actor.id
    case.updated_at = _now()
    await _audit(
        db,
        case,
        actor,
        "recognition_recorded",
        "dispute_case",
        str(case.id),
        before=before,
        after=_case_state(case),
        metadata={"notes": payload.notes},
    )
    return await refresh_case(db, case.id, actor)


async def recompute_case_amounts(case: DisputeCase) -> None:
    case.requested_amount = sum(
        (_money(item.claimed_amount) for item in case.anomalies), ZERO
    )
    case.recognized_amount = sum(
        (_money(item.recognized_amount) for item in case.anomalies), ZERO
    )
    case.recovered_amount = sum(
        (_money(item.recovered_amount) for item in case.anomalies), ZERO
    )
    case.unrecovered_amount = case.requested_amount - case.recovered_amount


def build_supplier_message(case: DisputeCase) -> tuple[str, str]:
    invoice_numbers = sorted(
        {
            str(row.evidence_snapshot.get("invoice_number"))
            for row in case.anomalies
            if row.evidence_snapshot.get("invoice_number")
        }
    )
    lines = [
        f"CONTESTAZIONE — {case.case_code}",
        f"Locale: {case.location_name or case.location_id}",
        f"Fornitore: {case.supplier_name or case.supplier_id}",
    ]
    if invoice_numbers:
        lines.append(f"Fatture: {', '.join(invoice_numbers)}")
    lines.extend(["", "Righe contestate:"])
    for row in case.anomalies:
        description = (
            row.evidence_snapshot.get("description")
            or row.evidence_snapshot.get("anomaly_type")
            or row.reason_snapshot
        )
        lines.append(
            f"- {description}: € {Decimal(row.claimed_amount):.2f}"
        )
    lines.extend(
        [
            "",
            f"Importo richiesto: € {Decimal(case.requested_amount):.2f}",
            "Richiediamo verifica e, se dovuta, emissione della relativa nota di credito.",
        ]
    )
    if case.due_date:
        lines.append(f"Riscontro richiesto entro: {case.due_date:%d/%m/%Y}")
    return (
        f"Contestazione {case.case_code} — richiesta nota di credito",
        "\n".join(lines),
    )


async def prepare_communication(
    db: AsyncSession,
    case: DisputeCase,
    payload: CommunicationPrepare,
    actor: Utente,
) -> DisputeCommunication:
    if case.status in TERMINAL_CASE_STATUSES:
        raise HTTPException(status_code=409, detail="terminal_case_immutable")
    if payload.channel not in {"whatsapp", "email", "pdf", "copy"}:
        raise HTTPException(status_code=422, detail="communication_channel_invalid")
    subject, generated_body = build_supplier_message(case)
    body = (payload.body_override or generated_body).strip()
    recipient = (payload.recipient or "").strip() or None
    if payload.channel in {"whatsapp", "email"} and not recipient:
        raise HTTPException(status_code=422, detail="communication_recipient_required")
    now = _now()
    communication = DisputeCommunication(
        dispute_case_id=case.id,
        channel=payload.channel,
        status="prepared",
        recipient=recipient,
        subject=(payload.subject or subject).strip(),
        body_snapshot=body,
        message_hash=sha256(body.encode("utf-8")).hexdigest(),
        created_by=actor.id,
        prepared_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(communication)
    await db.flush()
    await _audit(
        db,
        case,
        actor,
        "communication_prepared",
        "dispute_communication",
        str(communication.id),
        after={
            "channel": communication.channel,
            "status": communication.status,
            "message_hash": communication.message_hash,
        },
    )
    return communication


async def record_communication_event(
    db: AsyncSession,
    case: DisputeCase,
    communication: DisputeCommunication,
    action: str,
    actor: Utente,
) -> DisputeCase:
    rule = COMMUNICATION_ACTIONS.get(action)
    if not rule:
        raise HTTPException(status_code=422, detail="communication_action_invalid")
    if communication.dispute_case_id != case.id:
        raise HTTPException(status_code=409, detail="cross_case_communication")
    target_status, timestamp_field, target_rank = rule
    if target_rank < COMMUNICATION_RANK[communication.status]:
        raise HTTPException(status_code=409, detail="communication_state_regression")
    before_status = communication.status
    now = _now()
    communication.status = target_status
    if getattr(communication, timestamp_field) is None:
        setattr(communication, timestamp_field, now)
    communication.updated_at = now
    if action == "confirmed" and case.status == "ready_to_send":
        case.status = "sent"
        case.version += 1
        case.updated_by = actor.id
        case.updated_at = now
        await mark_source_anomalies_in_dispute(db, case, actor)
    await _audit(
        db,
        case,
        actor,
        f"communication_{action}",
        "dispute_communication",
        str(communication.id),
        before={"status": before_status},
        after={"status": communication.status},
    )
    return await refresh_case(db, case.id, actor)


async def record_supplier_response(
    db: AsyncSession,
    case: DisputeCase,
    payload: SupplierResponseCreate,
    actor: Utente,
) -> DisputeCase:
    if case.status in TERMINAL_CASE_STATUSES:
        raise HTTPException(status_code=409, detail="terminal_case_immutable")
    if payload.channel not in {"whatsapp", "email", "phone", "portal", "other"}:
        raise HTTPException(status_code=422, detail="response_channel_invalid")
    if payload.communication_id:
        communication = await db.get(
            DisputeCommunication, payload.communication_id
        )
        if not communication or communication.dispute_case_id != case.id:
            raise HTTPException(status_code=409, detail="cross_case_communication")
        communication.status = "response_received"
        communication.response_received_at = payload.received_at
        communication.updated_at = _now()
    if payload.attachment_id:
        attachment = await db.get(DisputeAttachment, payload.attachment_id)
        if not attachment or attachment.dispute_case_id != case.id:
            raise HTTPException(status_code=409, detail="cross_case_attachment")
    response = DisputeSupplierResponse(
        dispute_case_id=case.id,
        communication_id=payload.communication_id,
        attachment_id=payload.attachment_id,
        channel=payload.channel,
        responder_name=payload.responder_name,
        response_text=payload.response_text.strip(),
        received_at=payload.received_at,
        recorded_by=actor.id,
        created_at=_now(),
    )
    db.add(response)
    before = _case_state(case)
    if case.status in {"sent", "credit_note_expected"}:
        case.status = "supplier_replied"
        case.version += 1
        case.updated_by = actor.id
        case.updated_at = _now()
    await db.flush()
    await _audit(
        db,
        case,
        actor,
        "supplier_response_recorded",
        "supplier_response",
        str(response.id),
        before=before,
        after=_case_state(case),
        metadata={"channel": payload.channel},
    )
    return await refresh_case(db, case.id, actor)


async def create_attachment(
    db: AsyncSession,
    case: DisputeCase,
    actor: Utente,
    *,
    filename: str,
    content_type: str,
    content: bytes,
    description: str | None,
) -> DisputeAttachment:
    if case.status in TERMINAL_CASE_STATUSES:
        raise HTTPException(status_code=409, detail="terminal_case_immutable")
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="attachment_size_invalid")
    allowed = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/plain",
        "text/csv",
    }
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail="attachment_type_invalid")
    safe_name = filename.replace("\\", "_").replace("/", "_").strip()
    if not safe_name or len(safe_name) > 255:
        raise HTTPException(status_code=422, detail="attachment_filename_invalid")
    attachment = DisputeAttachment(
        dispute_case_id=case.id,
        filename=safe_name,
        content_type=content_type,
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        content=content,
        description=description,
        created_by=actor.id,
        created_at=_now(),
    )
    db.add(attachment)
    await db.flush()
    await _audit(
        db,
        case,
        actor,
        "attachment_added",
        "dispute_attachment",
        str(attachment.id),
        after={
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": attachment.size_bytes,
            "sha256": attachment.sha256,
        },
    )
    return attachment


async def create_credit_note(
    db: AsyncSession,
    case: DisputeCase,
    payload: CreditNoteCreate,
    actor: Utente,
) -> DisputeCase:
    if case.status not in {
        "sent",
        "supplier_replied",
        "credit_note_expected",
        "partially_recovered",
    }:
        raise HTTPException(status_code=409, detail="credit_note_not_allowed")
    if payload.source not in {"manual", "imported"}:
        raise HTTPException(status_code=422, detail="credit_note_source_invalid")
    if payload.fattura_id is not None:
        invoice = await db.get(Fattura, payload.fattura_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="credit_note_invoice_not_found")
        if (
            invoice.tipo_documento != TipoDocumento.TD04
            or invoice.location_id != case.location_id
            or invoice.fornitore_id != case.supplier_id
            or invoice.numero_documento != payload.document_number
            or invoice.data_documento != payload.issue_date
        ):
            raise HTTPException(
                status_code=409, detail="credit_note_invoice_context_mismatch"
            )
    duplicate = await db.scalar(
        select(func.count(DisputeCreditNote.id)).where(
            DisputeCreditNote.location_id == case.location_id,
            DisputeCreditNote.supplier_id == case.supplier_id,
            DisputeCreditNote.document_number == payload.document_number,
            DisputeCreditNote.issue_date == payload.issue_date,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="credit_note_duplicate")
    rows = {row.id: row for row in case.anomalies}
    if len({item.case_anomaly_id for item in payload.allocations}) != len(
        payload.allocations
    ):
        raise HTTPException(status_code=422, detail="duplicate_credit_allocation")
    allocated_total = sum(
        (_money(item.amount) for item in payload.allocations), ZERO
    )
    total_amount = _money(payload.total_amount)
    if allocated_total > total_amount:
        raise HTTPException(
            status_code=422, detail="credit_allocations_exceed_document"
        )
    now = _now()
    credit_note = DisputeCreditNote(
        dispute_case_id=case.id,
        location_id=case.location_id,
        supplier_id=case.supplier_id,
        fattura_id=payload.fattura_id,
        source=payload.source,
        status=(
            "allocated" if allocated_total == total_amount else "partially_allocated"
        ),
        document_number=payload.document_number.strip(),
        issue_date=payload.issue_date,
        total_amount=total_amount,
        notes=payload.notes,
        recorded_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(credit_note)
    await db.flush()
    before = _case_state(case)
    for item in payload.allocations:
        row = rows.get(item.case_anomaly_id)
        if not row:
            raise HTTPException(status_code=409, detail="cross_case_allocation")
        amount = _money(item.amount)
        remaining = _money(row.claimed_amount) - _money(row.recovered_amount)
        if amount > remaining:
            raise HTTPException(
                status_code=422, detail="credit_allocation_exceeds_claim"
            )
        row.recovered_amount = _money(row.recovered_amount) + amount
        if row.recognized_amount < row.recovered_amount:
            row.recognized_amount = row.recovered_amount
        db.add(
            DisputeCreditNoteAllocation(
                credit_note_id=credit_note.id,
                case_anomaly_id=row.id,
                amount=amount,
                created_by=actor.id,
                created_at=now,
            )
        )
    await recompute_case_amounts(case)
    case.status = (
        "recovered"
        if case.recovered_amount == case.requested_amount
        else "partially_recovered"
    )
    case.version += 1
    case.updated_by = actor.id
    case.updated_at = now
    await _audit(
        db,
        case,
        actor,
        "credit_note_recorded",
        "dispute_credit_note",
        str(credit_note.id),
        before=before,
        after=_case_state(case),
        metadata={
            "document_number": credit_note.document_number,
            "document_amount": str(credit_note.total_amount),
            "allocated_amount": str(allocated_total),
            "source": credit_note.source,
        },
    )
    return await refresh_case(db, case.id, actor)


async def get_communication(
    db: AsyncSession, communication_id: UUID
) -> DisputeCommunication:
    communication = await db.get(DisputeCommunication, communication_id)
    if not communication:
        raise HTTPException(status_code=404, detail="communication_not_found")
    return communication


async def get_attachment(
    db: AsyncSession, attachment_id: UUID, user: Utente
) -> DisputeAttachment:
    attachment = await db.get(DisputeAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    case = await db.get(DisputeCase, attachment.dispute_case_id)
    if not case:
        raise HTTPException(status_code=404, detail="dispute_case_not_found")
    assert_location_access(user, case.location_id)
    return attachment
