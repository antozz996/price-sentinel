"""Safe alert generation: detect and notify, never decide or match automatically."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AutomationAlert, AutomationRun
from app.models.disputes import DisputeCase
from app.models.fatture import Fattura
from app.models.liquidstock_integration import LiquidStockIntegrationEvent
from app.models.onboarding import LocationReconciliationSettings
from app.models.purchase_order_reconciliation import (
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
)
from app.models.utenti import Utente


MANAGED_ALERT_TYPES = {
    "reconciliation_stalled",
    "invoice_candidate_available",
    "important_anomaly",
    "dispute_due",
    "credit_note_missing",
    "integration_event_failed",
}


@dataclass(frozen=True)
class DetectedAlert:
    dedupe_key: str
    alert_type: str
    severity: str
    location_id: int | None
    entity_type: str
    entity_id: str
    title: str
    message: str
    details: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _detect_alerts(db: AsyncSession) -> list[DetectedAlert]:
    now = _now()
    found: list[DetectedAlert] = []
    settings_by_location = {
        row.location_id: row
        for row in (
            await db.scalars(select(LocationReconciliationSettings))
        ).all()
    }

    stale_rows = (
        await db.execute(
            select(PurchaseOrderReconciliation, LiquidStockVenueMapping)
            .join(
                LiquidStockVenueMapping,
                LiquidStockVenueMapping.liquidstock_venue_id
                == PurchaseOrderReconciliation.venue_id,
            )
            .where(
                PurchaseOrderReconciliation.status.in_(
                    ["pending", "awaiting_invoice"]
                ),
            )
        )
    ).all()
    for reconciliation, mapping in stale_rows:
        settings = settings_by_location.get(mapping.location_id)
        stalled_days = (
            settings.stalled_reconciliation_days if settings else 3
        )
        if reconciliation.updated_at >= now - timedelta(days=stalled_days):
            continue
        found.append(
            DetectedAlert(
                dedupe_key=f"reconciliation_stalled:{reconciliation.id}",
                alert_type="reconciliation_stalled",
                severity="warning",
                location_id=mapping.location_id,
                entity_type="reconciliation",
                entity_id=str(reconciliation.id),
                title="Riconciliazione ferma",
                message=(
                    "L’ordine attende una fattura compatibile da oltre tre giorni."
                ),
                details={
                    "status": reconciliation.status,
                    "liquidstock_supplier_order_id": str(
                        reconciliation.liquidstock_supplier_order_id
                    ),
                },
            )
        )

    waiting_rows = (
        await db.execute(
            select(PurchaseOrderReconciliation, LiquidStockVenueMapping)
            .join(
                LiquidStockVenueMapping,
                LiquidStockVenueMapping.liquidstock_venue_id
                == PurchaseOrderReconciliation.venue_id,
            )
            .where(
                PurchaseOrderReconciliation.fattura_id.is_(None),
                PurchaseOrderReconciliation.status.in_(
                    ["pending", "awaiting_invoice"]
                ),
                PurchaseOrderReconciliation.supplier_id.is_not(None),
            )
        )
    ).all()
    for reconciliation, mapping in waiting_rows:
        candidate_count = await db.scalar(
            select(func.count(Fattura.id)).where(
                Fattura.location_id == mapping.location_id,
                Fattura.fornitore_id == reconciliation.supplier_id,
                Fattura.data_documento >= reconciliation.created_at.date(),
                ~Fattura.id.in_(
                    select(PurchaseOrderReconciliation.fattura_id).where(
                        PurchaseOrderReconciliation.fattura_id.is_not(None)
                    )
                ),
            )
        )
        if candidate_count:
            found.append(
                DetectedAlert(
                    dedupe_key=f"invoice_candidate_available:{reconciliation.id}",
                    alert_type="invoice_candidate_available",
                    severity="info",
                    location_id=mapping.location_id,
                    entity_type="reconciliation",
                    entity_id=str(reconciliation.id),
                    title="Fattura candidata disponibile",
                    message=(
                        f"Sono disponibili {candidate_count} fatture candidate. "
                        "L’associazione resta manuale."
                    ),
                    details={"candidate_count": candidate_count},
                )
            )

    important_rows = (
        await db.execute(
            select(
                PurchaseOrderReconciliationAnomaly,
                LiquidStockVenueMapping.location_id,
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
                PurchaseOrderReconciliationAnomaly.workflow_status.notin_(
                    ["risolta", "ignorata"]
                ),
                PurchaseOrderReconciliationAnomaly.disputed_amount.is_not(None),
            )
        )
    ).all()
    for anomaly, location_id in important_rows:
        settings = settings_by_location.get(location_id)
        threshold = (
            Decimal(settings.important_anomaly_threshold)
            if settings
            else Decimal("50")
        )
        if Decimal(anomaly.disputed_amount) < threshold:
            continue
        found.append(
            DetectedAlert(
                dedupe_key=f"important_anomaly:{anomaly.id}",
                alert_type="important_anomaly",
                severity="critical",
                location_id=location_id,
                entity_type="reconciliation_anomaly",
                entity_id=str(anomaly.id),
                title="Anomalia economica importante",
                message=(
                    "È richiesta una revisione manuale per un’anomalia "
                    f"di € {Decimal(anomaly.disputed_amount):.2f}."
                ),
                details={
                    "anomaly_type": anomaly.anomaly_type,
                    "disputed_amount": str(anomaly.disputed_amount),
                },
            )
        )

    due_cases = (
        await db.scalars(
            select(DisputeCase).where(
                DisputeCase.status.notin_(["closed", "cancelled"]),
                DisputeCase.due_date.is_not(None),
                DisputeCase.due_date <= date.today() + timedelta(days=3),
            )
        )
    ).all()
    for case in due_cases:
        overdue = case.due_date < date.today()
        found.append(
            DetectedAlert(
                dedupe_key=f"dispute_due:{case.id}",
                alert_type="dispute_due",
                severity="critical" if overdue else "warning",
                location_id=case.location_id,
                entity_type="dispute_case",
                entity_id=str(case.id),
                title=(
                    "Contestazione scaduta"
                    if overdue
                    else "Contestazione prossima alla scadenza"
                ),
                message=f"La pratica {case.case_code} richiede attenzione.",
                details={
                    "case_code": case.case_code,
                    "due_date": case.due_date.isoformat(),
                    "status": case.status,
                },
            )
        )

    missing_notes = (
        await db.scalars(
            select(DisputeCase).where(
                DisputeCase.status.in_(
                    ["credit_note_expected", "partially_recovered"]
                ),
                DisputeCase.unrecovered_amount > 0,
            )
        )
    ).all()
    for case in missing_notes:
        settings = settings_by_location.get(case.location_id)
        missing_days = settings.missing_credit_note_days if settings else 7
        if case.updated_at >= now - timedelta(days=missing_days):
            continue
        found.append(
            DetectedAlert(
                dedupe_key=f"credit_note_missing:{case.id}",
                alert_type="credit_note_missing",
                severity="warning",
                location_id=case.location_id,
                entity_type="dispute_case",
                entity_id=str(case.id),
                title="Nota di credito ancora mancante",
                message=(
                    f"La pratica {case.case_code} ha ancora "
                    f"€ {Decimal(case.unrecovered_amount):.2f} da recuperare."
                ),
                details={
                    "case_code": case.case_code,
                    "unrecovered_amount": str(case.unrecovered_amount),
                },
            )
        )

    failed_events = (
        await db.scalars(
            select(LiquidStockIntegrationEvent).where(
                LiquidStockIntegrationEvent.processing_status == "failed",
                LiquidStockIntegrationEvent.received_at
                >= now - timedelta(days=30),
            )
        )
    ).all()
    for event in failed_events:
        found.append(
            DetectedAlert(
                dedupe_key=f"integration_event_failed:{event.external_event_id}",
                alert_type="integration_event_failed",
                severity="critical",
                location_id=None,
                entity_type="integration_event",
                entity_id=str(event.external_event_id),
                title="Evento LiquidStock non elaborato",
                message=(
                    "Un evento firmato non è stato proiettato. "
                    "Verificare il monitor integrazione senza rilanci casuali."
                ),
                details={
                    "event_type": event.event_type,
                    "error_code": event.processing_error,
                },
            )
        )
    return found


async def run_operational_monitor(db: AsyncSession) -> AutomationRun:
    """Run once with a transaction advisory lock to avoid duplicate schedulers."""
    started = _now()
    acquired = await db.scalar(
        select(func.pg_try_advisory_xact_lock(7_280_150))
    )
    run = AutomationRun(
        job_name="operational_monitor",
        status="running" if acquired else "skipped",
        started_at=started,
        completed_at=started if not acquired else None,
        alerts_detected=0,
        alerts_created=0,
        alerts_resolved=0,
        run_metadata={"decision_mode": "alerts_only"},
        created_at=started,
    )
    db.add(run)
    await db.flush()
    if not acquired:
        return run

    detected = await _detect_alerts(db)
    detected_keys = {item.dedupe_key for item in detected}
    created = 0
    for item in detected:
        alert = await db.scalar(
            select(AutomationAlert)
            .where(AutomationAlert.dedupe_key == item.dedupe_key)
            .with_for_update()
        )
        if alert is None:
            alert = AutomationAlert(
                dedupe_key=item.dedupe_key,
                first_detected_at=started,
                created_at=started,
            )
            db.add(alert)
            created += 1
        alert.alert_type = item.alert_type
        alert.severity = item.severity
        alert.location_id = item.location_id
        alert.entity_type = item.entity_type
        alert.entity_id = item.entity_id
        alert.title = item.title
        alert.message = item.message
        alert.details = item.details
        alert.last_detected_at = started
        alert.updated_at = started
        if alert.status == "resolved":
            alert.status = "open"
            alert.resolved_at = None

    active_rows = (
        await db.scalars(
            select(AutomationAlert)
            .where(
                AutomationAlert.alert_type.in_(MANAGED_ALERT_TYPES),
                AutomationAlert.status.in_(["open", "acknowledged"]),
            )
            .with_for_update()
        )
    ).all()
    resolved = 0
    for alert in active_rows:
        if alert.dedupe_key not in detected_keys:
            alert.status = "resolved"
            alert.resolved_at = started
            alert.updated_at = started
            resolved += 1

    run.status = "completed"
    run.completed_at = _now()
    run.alerts_detected = len(detected)
    run.alerts_created = created
    run.alerts_resolved = resolved
    return run


async def acknowledge_alert(
    db: AsyncSession, alert: AutomationAlert, actor: Utente
) -> AutomationAlert:
    if alert.status == "resolved":
        return alert
    now = _now()
    alert.status = "acknowledged"
    alert.acknowledged_by = actor.id
    alert.acknowledged_at = now
    alert.updated_at = now
    await db.flush()
    return alert
