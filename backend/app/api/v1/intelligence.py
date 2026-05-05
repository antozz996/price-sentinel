"""
Price Sentinel — Intelligence Router (Sprint 4).
Espone gli endpoint per la Dashboard Admin, KPI e Cross-Location Tracker.
"""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_db
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.location import Location
from app.models.listino import ListinoMaster
from fastapi.responses import Response
from app.services.pdf_generator import generate_vendor_passport_pdf

router = APIRouter()


@router.get("/kpi", summary="Kpi Economici Principali")
async def get_kpi(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict[str, Any]:
    """
    Ritorna gli indicatori economici:
    - Euro Recuperati Totali (NC registrate)
    - Euro In Contestazione (Anomalie in_reclamo)
    - Euro A Rischio (Anomalie contestate ma non ancora in reclamo)
    """
    # Recuperati Totali
    recuperati_res = await db.execute(
        select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
    )
    recuperati = recuperati_res.scalar()

    # In Contestazione
    contestazione_res = await db.execute(
        select(func.coalesce(func.sum(Anomalia.delta_totale), 0))
        .where(Anomalia.stato_validazione == StatoValidazione.in_reclamo)
    )
    contestazione = contestazione_res.scalar()

    # A Rischio
    rischio_res = await db.execute(
        select(func.coalesce(func.sum(Anomalia.delta_totale), 0))
        .where(Anomalia.stato_validazione == StatoValidazione.contestata)
    )
    rischio = rischio_res.scalar()

    # In attesa Manager
    attesa_res = await db.execute(
        select(func.coalesce(func.sum(Anomalia.delta_totale), 0))
        .where(Anomalia.stato_validazione == StatoValidazione.da_verificare)
    )
    attesa = attesa_res.scalar()

    return {
        "euro_recuperati": float(recuperati),
        "euro_in_contestazione": float(contestazione),
        "euro_a_rischio": float(rischio),
        "euro_attesa_manager": float(attesa)
    }


@router.get("/expiring-protocols", summary="Widget Scadenze Contratti")
async def get_expiring_protocols(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Lista semaforica dei ListinoMaster in scadenza nei prossimi 30 giorni.
    """
    oggi = date.today()
    scadenza_limite = oggi + timedelta(days=30)
    
    res = await db.execute(
        select(ListinoMaster)
        .where(and_(
            ListinoMaster.data_scadenza <= scadenza_limite,
            ListinoMaster.data_scadenza >= oggi,
            ListinoMaster.is_active == True
        ))
        .order_by(ListinoMaster.data_scadenza.asc())
    )
    listini = res.scalars().all()
    
    result = []
    for l in listini:
        days_left = (l.data_scadenza - oggi).days
        color = "red" if days_left < 7 else ("yellow" if days_left < 15 else "green")
        result.append({
            "id": l.id,
            "sku_interno": l.sku_interno,
            "fornitore_id": l.fornitore_id,
            "data_scadenza": l.data_scadenza,
            "days_left": days_left,
            "color": color
        })
    return result


@router.get("/cross-location", summary="Cross-Location Tracker")
async def get_cross_location_matrix(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Matrice di intelligence negoziale.
    Ritorna l'ultimo prezzo di acquisto di uno sku per ogni location.
    I dati permettono al frontend di costruire una griglia Prodotti x Location.
    """
    # Vogliamo l'ultimo prezzo normalizzato per (sku_interno, location_id).
    # Group By SKU e Location, max ID
    subquery = (
        select(
            RigaFattura.sku_interno,
            Fattura.location_id,
            func.max(RigaFattura.id).label("max_riga_id")
        )
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(RigaFattura.stato_matching == StatoMatching.matched)
        .where(RigaFattura.sku_interno.isnot(None))
        .group_by(RigaFattura.sku_interno, Fattura.location_id)
        .subquery()
    )
    
    stmt = (
        select(RigaFattura.sku_interno, Fattura.location_id, RigaFattura.prezzo_netto_normalizzato)
        .join(subquery, RigaFattura.id == subquery.c.max_riga_id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
    )
    
    res = await db.execute(stmt)
    records = res.all()
    
    
    # Costruiamo la risposta JSON formattata per la griglia UI
    matrix = {}
    for sku, loc_id, price in records:
        if sku not in matrix:
            matrix[sku] = {}
        matrix[sku][loc_id] = float(price)
        
    return matrix


@router.get("/export-vendor-passport/{fornitore_id}", summary="Download Vendor Passport PDF")
async def export_vendor_passport(
    fornitore_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Genera il PDF Business Intelligence per il fornitore.
    """
    from app.models.fornitori import Fornitore
    fornitore = await db.scalar(select(Fornitore).where(Fornitore.id == fornitore_id))
    if not fornitore:
        from fastapi import HTTPException
        raise HTTPException(404, "Fornitore non trovato")
        
    # Calcolo assortimento aggregato senza esporre prezzi
    stmt = (
        select(Location.nome_struttura)
        .join(Fattura, Fattura.location_id == Location.id)
        .where(Fattura.fornitore_id == fornitore_id)
        .distinct()
    )
    locations = (await db.scalars(stmt)).all()
    
    # Questo è un mockup di astrazione in quanto richiede incrociare 
    # unità di misura in volumi per la specifica
    vendor_data = {
        "vendor_name": fornitore.nome_azienda,
        "location_servite": len(locations),
        "frequenza": "Settimanale (stimata)",
        "assorbimento": [
            {"categoria": "Volume Acquistato YTD (Mock)", "volume": 12000, "unita": "Pz"}
        ]
    }
    
    pdf_bytes = generate_vendor_passport_pdf(vendor_data)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Vendor_Passport_{fornitore_id}.pdf"
        }
    )
