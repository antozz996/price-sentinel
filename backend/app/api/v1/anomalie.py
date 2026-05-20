"""
Price Sentinel — Anomalie Router.
Workflow a stati completo — Spec §4.1, §4.2, §4.3.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_manager
from app.database import get_db
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione
from app.models.utenti import Utente
from app.schemas.anomalie import (
    AnomaliaAzione,
    AnomaliaEscalation,
    AnomaliaResponse,
    NotaDiCreditoCreate,
    NotaDiCreditoResponse,
)
from app.services.notifications import notify_admin_escalation

router = APIRouter()


# ─────────────────────────────────────────────
# Lettura Anomalie
# ─────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[AnomaliaResponse],
    summary="Lista anomalie",
)
async def list_anomalie(
    response: Response,
    stato: str | None = Query(None, description="Filtra per stato validazione"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.fatture import RigaFattura, Fattura
    from app.models.fornitori import Fornitore

    query = select(Anomalia).options(
        selectinload(Anomalia.riga_fattura).selectinload(RigaFattura.fattura).selectinload(Fattura.fornitore)
    ).order_by(Anomalia.id.desc())

    if stato:
        query = query.where(Anomalia.stato_validazione == StatoValidazione(stato))

    if current_user.ruolo.value == "manager":
        query = (
            query.join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
            .join(Fattura, RigaFattura.fattura_id == Fattura.id)
            .where(Fattura.location_id == current_user.location_id)
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    # Slice results
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get(
    "/{anomalia_id}",
    response_model=AnomaliaResponse,
    summary="Dettaglio anomalia",
)
async def get_anomalia(
    anomalia_id: int,
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.fatture import RigaFattura, Fattura
    from app.models.fornitori import Fornitore

    query = select(Anomalia).options(
        selectinload(Anomalia.riga_fattura).selectinload(RigaFattura.fattura).selectinload(Fattura.fornitore)
    ).where(Anomalia.id == anomalia_id)

    if _user.ruolo.value == "manager":
        query = (
            query.join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
            .join(Fattura, RigaFattura.fattura_id == Fattura.id)
            .where(Fattura.location_id == _user.location_id)
        )
    result = await db.execute(query)
    anomalia = result.scalar_one_or_none()
    if not anomalia:
        raise HTTPException(status_code=404, detail="Anomalia non trovata")
    return anomalia


# ─────────────────────────────────────────────
# Stadio 1 — Validazione Manager (Spec §4.2)
# ─────────────────────────────────────────────

@router.post(
    "/{anomalia_id}/azione",
    response_model=AnomaliaResponse,
    summary="Azione Manager su anomalia",
    description="Segnala / Accetta / Proponi Aggiornamento / Parcheggia — Spec §4.2",
)
async def azione_manager(
    anomalia_id: int,
    data: AnomaliaAzione,
    manager: Utente = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
):
    from app.models.fatture import RigaFattura, Fattura
    conditions = [Anomalia.id == anomalia_id]
    if manager.ruolo.value != "admin":
        conditions.append(Fattura.location_id == manager.location_id)

    query = (
        select(Anomalia)
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(and_(*conditions))
    )
    result = await db.execute(query)
    anomalia = result.scalar_one_or_none()
    if not anomalia:
        raise HTTPException(status_code=404, detail="Anomalia non trovata")

    if anomalia.stato_validazione not in (
        StatoValidazione.da_verificare,
        StatoValidazione.in_parking,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Anomalia in stato '{anomalia.stato_validazione.value}' — azione non consentita",
        )

    now = datetime.now(timezone.utc)

    match data.azione:
        case "segnala":
            anomalia.stato_validazione = StatoValidazione.contestata
            anomalia.validato_da_user_id = manager.id
            anomalia.validato_at = now
            
            # Notifica Admin via Telegram
            from app.models.fatture import RigaFattura, Fattura
            from app.models.fornitori import Fornitore
            from app.models.location import Location
            
            # Ottieni info per notifica
            res = await db.execute(
                select(Anomalia, RigaFattura, Fattura, Fornitore, Location)
                .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
                .join(Fattura, RigaFattura.fattura_id == Fattura.id)
                .join(Fornitore, Fattura.fornitore_id == Fornitore.id)
                .join(Location, Fattura.location_id == Location.id)
                .where(Anomalia.id == anomalia_id)
            )
            row = res.first()
            if row:
                _, riga, _f, forn, loc = row
                
                admin_res = await db.execute(select(Utente).where(Utente.ruolo == "admin"))
                admin = admin_res.scalars().first()
                
                if admin and admin.telegram_chat_id:
                    import asyncio
                    asyncio.create_task(
                        notify_admin_escalation(
                            chat_id=admin.telegram_chat_id,
                            location_name=loc.nome_struttura,
                            fornitore_nome=forn.nome_azienda,
                            prodotto=riga.descrizione_fornitore_raw,
                            delta=float(anomalia.delta_prezzo),
                        )
                    )

        case "accetta":
            if not data.nota:
                raise HTTPException(
                    status_code=400,
                    detail="Nota obbligatoria per accettazione — Spec §4.2",
                )
            anomalia.stato_validazione = StatoValidazione.accettata
            anomalia.nota_manager = data.nota
            anomalia.validato_da_user_id = manager.id
            anomalia.validato_at = now

        case "proponi_aggiornamento":
            anomalia.stato_validazione = StatoValidazione.proposta_aggiornamento
            anomalia.nota_manager = data.nota
            anomalia.validato_da_user_id = manager.id
            anomalia.validato_at = now

        case "parcheggia":
            anomalia.stato_validazione = StatoValidazione.in_parking
            anomalia.validato_da_user_id = manager.id
            anomalia.validato_at = now

        case _:
            raise HTTPException(
                status_code=400,
                detail="Azione non valida. Usa: segnala, accetta, proponi_aggiornamento, parcheggia",
            )

    await db.flush()
    await db.refresh(anomalia)
    return anomalia


# ─────────────────────────────────────────────
# Stadio 2 — Escalation Admin (Spec §4.3)
# ─────────────────────────────────────────────

@router.post(
    "/{anomalia_id}/escalation",
    response_model=AnomaliaResponse,
    summary="Escalation Admin",
    description="Reclamo globale o registrazione NC — Spec §4.3",
)
async def escalation_admin(
    anomalia_id: int,
    data: AnomaliaEscalation,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Anomalia).where(Anomalia.id == anomalia_id))
    anomalia = result.scalar_one_or_none()
    if not anomalia:
        raise HTTPException(status_code=404, detail="Anomalia non trovata")

    if anomalia.stato_validazione != StatoValidazione.contestata:
        raise HTTPException(
            status_code=400,
            detail="Solo anomalie in stato 'contestata' possono essere escalate",
        )

    now = datetime.now(timezone.utc)

    match data.azione:
        case "reclamo":
            anomalia.stato_validazione = StatoValidazione.in_reclamo
            anomalia.gestito_da_admin_id = admin.id
            anomalia.gestito_at = now

        case _:
            raise HTTPException(
                status_code=400,
                detail="Azione non valida. Usa: reclamo",
            )

    await db.flush()
    await db.refresh(anomalia)
    return anomalia


# ─────────────────────────────────────────────
# Note di Credito (Spec §4.3)
# ─────────────────────────────────────────────

@router.post(
    "/note-credito",
    response_model=NotaDiCreditoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registra Nota di Credito",
    description="Chiude l'anomalia e aggiorna il contatore Soldi Recuperati — Spec §4.3",
)
async def registra_nota_credito(
    data: NotaDiCreditoCreate,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Verifica anomalia esiste e in stato corretto
    result = await db.execute(
        select(Anomalia).where(Anomalia.id == data.anomalia_id)
    )
    anomalia = result.scalar_one_or_none()
    if not anomalia:
        raise HTTPException(status_code=404, detail="Anomalia non trovata")

    if anomalia.stato_validazione != StatoValidazione.in_reclamo:
        raise HTTPException(
            status_code=400,
            detail="NC registrabile solo su anomalie in stato 'in_reclamo'",
        )

    # Crea NC
    nc = NotaDiCredito(
        anomalia_id=data.anomalia_id,
        importo_recuperato=data.importo_recuperato,
        data_emissione_nc=data.data_emissione_nc,
        data_registrazione=date.today(),
        numero_nc=data.numero_nc,
        registrato_da_admin_id=admin.id,
    )
    db.add(nc)

    # Chiudi anomalia → risolta
    anomalia.stato_validazione = StatoValidazione.risolta
    anomalia.gestito_da_admin_id = admin.id
    anomalia.gestito_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(nc)
    return nc


@router.get(
    "/note-credito/totale-recuperato",
    summary="Totale Soldi Recuperati",
    description="Somma di tutti gli importi NC registrati — contatore Spec §4.3",
)
async def totale_recuperato(
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    result = await db.execute(
        select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
    )
    totale = result.scalar()
    return {"totale_recuperato": float(totale)}
