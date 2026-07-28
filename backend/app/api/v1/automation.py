"""In-app operational alerts and manually triggerable safe monitor."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.automation import AutomationAlert, AutomationRun
from app.models.utenti import Utente
from app.schemas.automation import AutomationAlertOut, AutomationRunOut
from app.services.automation import acknowledge_alert, run_operational_monitor


router = APIRouter()


@router.get("/alerts", response_model=list[AutomationAlertOut])
async def list_alerts(
    status: str | None = Query(None, pattern="^(open|acknowledged|resolved)$"),
    limit: int = Query(100, ge=1, le=250),
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statement = select(AutomationAlert)
    if user.ruolo.value != "admin":
        statement = statement.where(
            AutomationAlert.location_id == user.location_id
        )
    if status:
        statement = statement.where(AutomationAlert.status == status)
    return (
        await db.scalars(
            statement.order_by(
                AutomationAlert.status,
                AutomationAlert.last_detected_at.desc(),
            ).limit(limit)
        )
    ).all()


@router.post("/alerts/{alert_id}/acknowledge", response_model=AutomationAlertOut)
async def acknowledge(
    alert_id: UUID,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    alert = await db.scalar(
        select(AutomationAlert)
        .where(AutomationAlert.id == alert_id)
        .with_for_update()
    )
    if not alert:
        raise HTTPException(status_code=404, detail="automation_alert_not_found")
    if (
        user.ruolo.value != "admin"
        and alert.location_id != user.location_id
    ):
        raise HTTPException(status_code=403, detail="automation_alert_forbidden")
    return await acknowledge_alert(db, alert, user)


@router.post("/run", response_model=AutomationRunOut)
async def run_monitor(
    _: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await run_operational_monitor(db)


@router.get("/runs", response_model=list[AutomationRunOut])
async def list_runs(
    limit: int = Query(30, ge=1, le=100),
    _: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return (
        await db.scalars(
            select(AutomationRun)
            .order_by(AutomationRun.started_at.desc())
            .limit(limit)
        )
    ).all()
