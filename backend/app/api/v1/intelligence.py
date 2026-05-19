"""
Price Sentinel — Intelligence Router (Sprint 4).
Espone gli endpoint per la Dashboard Admin, KPI e Cross-Location Tracker.
"""

from datetime import date, timedelta, datetime, timezone
from typing import Any
from io import BytesIO

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, and_, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, get_current_user
from app.database import get_db
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione, ApprovazionePrezzo
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.location import Location
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from fastapi.responses import Response, StreamingResponse
from app.services.pdf_generator import generate_vendor_passport_pdf
from app.schemas.approvazioni import ApprovazionePrezzoCreate, ApprovazionePrezzoResponse

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

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
    # Optimized single query for Anomalia states
    anomalie_stmt = select(
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.in_reclamo, Anomalia.delta_totale), else_=0)), 0).label("in_contestazione"),
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.contestata, Anomalia.delta_totale), else_=0)), 0).label("a_rischio"),
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.da_verificare, Anomalia.delta_totale), else_=0)), 0).label("attesa_manager"),
    )
    anomalie_res = await db.execute(anomalie_stmt)
    anomalie_row = anomalie_res.one()

    # Recuperati Totali (from NotaDiCredito table)
    recuperati_res = await db.execute(
        select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
    )
    recuperati = recuperati_res.scalar()

    return {
        "euro_recuperati": float(recuperati),
        "euro_in_contestazione": float(anomalie_row.in_contestazione),
        "euro_a_rischio": float(anomalie_row.a_rischio),
        "euro_attesa_manager": float(anomalie_row.attesa_manager)
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
            ListinoMaster.data_scadenza >= oggi
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


# ─────────────────────────────────────────────
# 1. Gestione Approvazioni Prezzi Manuali
# ─────────────────────────────────────────────

@router.post("/approvazioni", response_model=ApprovazionePrezzoResponse, summary="Crea o aggiorna approvazione prezzo")
async def create_approvazione(
    data: ApprovazionePrezzoCreate,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Cerca se esiste gia'
    stmt = select(ApprovazionePrezzo).where(
        and_(
            ApprovazionePrezzo.sku_interno == data.sku_interno,
            ApprovazionePrezzo.descrizione_orig == data.descrizione_orig,
            ApprovazionePrezzo.mese == data.mese,
        )
    )
    res = await db.execute(stmt)
    appr = res.scalar_one_or_none()
    
    if appr:
        appr.prezzo_approvato = data.prezzo_approvato
        appr.stato = data.stato
    else:
        appr = ApprovazionePrezzo(
            sku_interno=data.sku_interno,
            descrizione_orig=data.descrizione_orig,
            mese=data.mese,
            prezzo_approvato=data.prezzo_approvato,
            stato=data.stato,
            created_at=datetime.now(timezone.utc),
        )
        db.add(appr)

    # ── SPEC §5.1: Aggiornamento Automatico ListinoMaster ──
    if data.stato.upper() in ("APPROVATO", "ACCETTATO"):
        # Cerca listino master attivo
        listino_stmt = select(ListinoMaster).where(
            and_(
                ListinoMaster.sku_interno == data.sku_interno,
                ListinoMaster.data_scadenza.is_(None)
            )
        ).limit(1)
        listino_res = await db.execute(listino_stmt)
        listino_active = listino_res.scalar_one_or_none()

        if listino_active:
            if float(listino_active.prezzo_pattuito) != float(data.prezzo_approvato):
                # Chiude la validita' del record corrente (Append-Only)
                listino_active.data_scadenza = date.today()
                
                # Crea nuovo record con prezzo aggiornato
                new_list = ListinoMaster(
                    fornitore_id=listino_active.fornitore_id,
                    sku_interno=data.sku_interno,
                    descrizione=listino_active.descrizione,
                    prezzo_pattuito=data.prezzo_approvato,
                    unita_misura=listino_active.unita_misura,
                    data_inizio_validita=date.today(),
                    data_scadenza=None
                )
                db.add(new_list)
        else:
            # Fallback: cerca una riga fattura recente per ottenere il fornitore_id e dettagli omologhi
            rf_stmt = (
                select(RigaFattura)
                .join(Fattura)
                .where(RigaFattura.sku_interno == data.sku_interno)
                .limit(1)
            )
            rf_res = await db.execute(rf_stmt)
            rf_item = rf_res.scalar_one_or_none()
            if rf_item and rf_item.fattura:
                new_list = ListinoMaster(
                    fornitore_id=rf_item.fattura.fornitore_id,
                    sku_interno=data.sku_interno,
                    descrizione=rf_item.descrizione_fornitore_raw or data.descrizione_orig,
                    prezzo_pattuito=data.prezzo_approvato,
                    unita_misura=rf_item.unita_misura_fattura or "Pz",
                    data_inizio_validita=date.today(),
                    data_scadenza=None
                )
                db.add(new_list)
        
    await db.flush()
    await db.refresh(appr)
    return appr


@router.get("/approvazioni", response_model=list[ApprovazionePrezzoResponse], summary="Lista approvazioni prezzi")
async def list_approvazioni(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApprovazionePrezzo).order_by(ApprovazionePrezzo.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/price-trend/{sku_interno}", summary="Trend Storico Prezzi per SKU")
async def get_price_trend(
    sku_interno: str,
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Recupera lo storico degli acquisti cronologicamente
    stmt = (
        select(
            Fattura.data_documento,
            RigaFattura.prezzo_netto_normalizzato,
            RigaFattura.quantita,
            Fornitore.nome_azienda.label("fornitore_nome")
        )
        .join(RigaFattura, RigaFattura.fattura_id == Fattura.id)
        .join(Fornitore, Fattura.fornitore_id == Fornitore.id)
        .where(
            and_(
                RigaFattura.sku_interno == sku_interno,
                RigaFattura.stato_matching == "matched"
            )
        )
        .order_by(Fattura.data_documento.asc())
    )
    res = await db.execute(stmt)
    history = res.all()
    
    # Recupera il listino attivo corrente
    listino_stmt = select(ListinoMaster).where(
        and_(
            ListinoMaster.sku_interno == sku_interno,
            ListinoMaster.data_scadenza.is_(None)
        )
    ).limit(1)
    listino_res = await db.execute(listino_stmt)
    listino_active = listino_res.scalar_one_or_none()
    prezzo_contratto = float(listino_active.prezzo_pattuito) if listino_active else None

    points = []
    for r in history:
        points.append({
            "data": r.data_documento.isoformat() if isinstance(r.data_documento, date) else str(r.data_documento),
            "prezzo_pagato": float(r.prezzo_netto_normalizzato),
            "quantita": float(r.quantita),
            "fornitore": r.fornitore_nome,
            "prezzo_contratto": prezzo_contratto
        })
        
    return {
        "sku_interno": sku_interno,
        "prodotto_nome": listino_active.descrizione if listino_active else sku_interno,
        "prezzo_contratto_corrente": prezzo_contratto,
        "history": points
    }


# ─────────────────────────────────────────────
# 2. Audit & Anomalie Pricing (ConfrontoPrezzi)
# ─────────────────────────────────────────────

@router.get("/pricing-audit", summary="Audit e Rilevamento Anomalie di Pricing")
async def get_pricing_audit(
    location_id: int | None = Query(None),
    anno: str | None = Query(None),
    soglia: float = Query(5.0, description="Soglia percentuale minima di rincaro"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sql = """
    WITH vendite_mensili AS (
        SELECT 
            rf.sku_interno as prodotto_id,
            rf.descrizione_fornitore_raw as nome_normalizzato,
            fo.nome_azienda as fornitore_ragione_sociale,
            f.fornitore_id,
            to_char(f.data_documento, 'YYYY-MM') as mese,
            AVG(rf.prezzo_netto_normalizzato) as prezzo_medio,
            SUM(rf.quantita) as qta_mese_corrente
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        JOIN fornitori fo ON f.fornitore_id = fo.id
        WHERE rf.sku_interno IS NOT NULL
          AND (:location_id IS NULL OR f.location_id = :location_id)
          AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
        GROUP BY rf.sku_interno, rf.descrizione_fornitore_raw, f.fornitore_id, fo.nome_azienda, to_char(f.data_documento, 'YYYY-MM')
    ),
    lagged_prezzi AS (
        SELECT 
            v.*,
            LAG(prezzo_medio, 1) OVER (PARTITION BY prodotto_id, fornitore_id ORDER BY mese) as prezzo_precedente_lag
        FROM vendite_mensili v
    )
    SELECT 
        lp.prodotto_id as sku_interno,
        lp.nome_normalizzato,
        lp.fornitore_id,
        lp.fornitore_ragione_sociale,
        lp.mese,
        lp.prezzo_medio,
        lp.qta_mese_corrente,
        lp.prezzo_precedente_lag,
        lc.prezzo_pattuito as prezzo_concordato,
        COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag) as prezzo_precedente,
        (SELECT MIN(rf2.prezzo_netto_normalizzato) FROM righe_fattura rf2 JOIN fatture f2 ON rf2.fattura_id = f2.id WHERE rf2.sku_interno = lp.prodotto_id) as hist_prezzo_min,
        (SELECT MAX(rf2.prezzo_netto_normalizzato) FROM righe_fattura rf2 JOIN fatture f2 ON rf2.fattura_id = f2.id WHERE rf2.sku_interno = lp.prodotto_id) as hist_prezzo_max,
        ap.stato
    FROM lagged_prezzi lp
    LEFT JOIN listino_master lc ON lp.prodotto_id = lc.sku_interno AND lp.fornitore_id = lc.fornitore_id
    LEFT JOIN approvazioni_prezzo ap ON lp.prodotto_id = ap.sku_interno AND lp.nome_normalizzato = ap.descrizione_orig AND lp.mese = ap.mese
    WHERE COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag) IS NOT NULL
      AND lp.prezzo_medio > COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)
      AND (((lp.prezzo_medio - COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) / COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) * 100) >= :soglia
    ORDER BY lp.mese DESC, lp.prodotto_id ASC
    LIMIT :limit OFFSET :offset
    """
    
    # Run total count query
    count_sql = f"""
    SELECT COUNT(*) FROM (
        WITH vendite_mensili AS (
            SELECT 
                rf.sku_interno as prodotto_id,
                rf.descrizione_fornitore_raw as nome_normalizzato,
                f.fornitore_id,
                to_char(f.data_documento, 'YYYY-MM') as mese,
                AVG(rf.prezzo_netto_normalizzato) as prezzo_medio
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            WHERE rf.sku_interno IS NOT NULL
              AND (:location_id IS NULL OR f.location_id = :location_id)
              AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
            GROUP BY rf.sku_interno, rf.descrizione_fornitore_raw, f.fornitore_id, to_char(f.data_documento, 'YYYY-MM')
        ),
        lagged_prezzi AS (
            SELECT 
                v.*,
                LAG(prezzo_medio, 1) OVER (PARTITION BY prodotto_id, fornitore_id ORDER BY mese) as prezzo_precedente_lag
            FROM vendite_mensili v
        )
        SELECT lp.prodotto_id
        FROM lagged_prezzi lp
        LEFT JOIN listino_master lc ON lp.prodotto_id = lc.sku_interno AND lp.fornitore_id = lc.fornitore_id
        WHERE COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag) IS NOT NULL
          AND lp.prezzo_medio > COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)
          AND (((lp.prezzo_medio - COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) / COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) * 100) >= :soglia
    ) as t
    """
    
    params = {
        "location_id": location_id,
        "anno": anno,
        "soglia": soglia,
    }
    
    # Counts
    count_res = await db.execute(text(count_sql), params)
    total = count_res.scalar() or 0
    
    params_with_limits = {**params, "limit": limit, "offset": offset}
    res = await db.execute(text(sql), params_with_limits)
    
    results = []
    for r in res.all():
        prezzo_medio = float(r.prezzo_medio)
        prezzo_precedente = float(r.prezzo_precedente)
        rincaro_unitario = prezzo_medio - prezzo_precedente
        spreco_mensile = rincaro_unitario * float(r.qta_mese_corrente)
        proiezione_annua = spreco_mensile * 12
        
        results.append({
            "sku_interno": r.sku_interno,
            "nome_normalizzato": r.nome_normalizzato,
            "fornitore_id": r.fornitore_id,
            "fornitore_ragione_sociale": r.fornitore_ragione_sociale,
            "mese": r.mese,
            "prezzo_medio": prezzo_medio,
            "qta_mese_corrente": float(r.qta_mese_corrente),
            "prezzo_precedente": prezzo_precedente,
            "rincaro_unitario": rincaro_unitario,
            "spreco_mensile": spreco_mensile,
            "proiezione_annua": proiezione_annua,
            "hist_prezzo_min": float(r.hist_prezzo_min) if r.hist_prezzo_min is not None else prezzo_medio,
            "hist_prezzo_max": float(r.hist_prezzo_max) if r.hist_prezzo_max is not None else prezzo_medio,
            "stato": r.stato or "PENDING"
        })
        
    return {"total": total, "results": results}


# ─────────────────────────────────────────────
# 3. Classifica Efficienza Locali
# ─────────────────────────────────────────────

@router.get("/efficiency-leaderboard", summary="Classifica Efficienza Locali")
async def get_efficiency_leaderboard(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sql = """
    WITH hist_min AS (
        SELECT 
            sku_interno,
            MIN(prezzo_netto_normalizzato) as hist_prezzo_min
        FROM righe_fattura
        WHERE sku_interno IS NOT NULL AND stato_matching = 'matched'
        GROUP BY sku_interno
    ),
    purchases AS (
        SELECT 
            f.location_id,
            loc.nome_struttura,
            rf.id as riga_id,
            rf.prezzo_netto_normalizzato,
            hm.hist_prezzo_min,
            CASE WHEN rf.prezzo_netto_normalizzato <= (hm.hist_prezzo_min * 1.05) THEN 1 ELSE 0 END as is_optimal
        FROM righe_fattura rf
        JOIN hist_min hm ON rf.sku_interno = hm.sku_interno
        JOIN fatture f ON rf.fattura_id = f.id
        JOIN location loc ON f.location_id = loc.id
        WHERE rf.stato_matching = 'matched'
    )
    SELECT 
        location_id,
        nome_struttura,
        COUNT(riga_id) as totali,
        SUM(is_optimal) as ottimali,
        ROUND((SUM(is_optimal)::numeric / COUNT(riga_id)::numeric) * 100, 2) as score
    FROM purchases
    GROUP BY location_id, nome_struttura
    ORDER BY score DESC
    """
    res = await db.execute(text(sql))
    
    leaderboard = []
    for i, r in enumerate(res.all()):
        rank = i + 1
        medal = "🏆" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
        leaderboard.append({
            "rank": rank,
            "medal": medal,
            "location_id": r.location_id,
            "nome_struttura": r.nome_struttura,
            "totali": r.totali,
            "ottimali": int(r.ottimali or 0),
            "score": float(r.score or 0)
        })
    return leaderboard


# ─────────────────────────────────────────────
# 4. Esporta Excel di Contestazione (openpyxl)
# ─────────────────────────────────────────────

@router.get("/export-dispute-excel", summary="Esporta Excel Contestazione")
async def export_dispute_excel(
    location_id: int | None = Query(None),
    anno: str | None = Query(None),
    soglia: float = Query(5.0),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sql = """
    WITH vendite_mensili AS (
        SELECT 
            rf.sku_interno as prodotto_id,
            rf.descrizione_fornitore_raw as nome_normalizzato,
            fo.nome_azienda as fornitore_ragione_sociale,
            f.fornitore_id,
            to_char(f.data_documento, 'YYYY-MM') as mese,
            AVG(rf.prezzo_netto_normalizzato) as prezzo_medio,
            SUM(rf.quantita) as qta_mese_corrente
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        JOIN fornitori fo ON f.fornitore_id = fo.id
        WHERE rf.sku_interno IS NOT NULL
          AND (:location_id IS NULL OR f.location_id = :location_id)
          AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
        GROUP BY rf.sku_interno, rf.descrizione_fornitore_raw, f.fornitore_id, fo.nome_azienda, to_char(f.data_documento, 'YYYY-MM')
    ),
    lagged_prezzi AS (
        SELECT 
            v.*,
            LAG(prezzo_medio, 1) OVER (PARTITION BY prodotto_id, fornitore_id ORDER BY mese) as prezzo_precedente_lag
        FROM vendite_mensili v
    )
    SELECT 
        lp.prodotto_id as sku_interno,
        lp.nome_normalizzato,
        lp.fornitore_id,
        lp.fornitore_ragione_sociale,
        lp.mese,
        lp.prezzo_medio,
        lp.qta_mese_corrente,
        lp.prezzo_precedente_lag,
        lc.prezzo_pattuito as prezzo_concordato,
        COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag) as prezzo_precedente
    FROM lagged_prezzi lp
    LEFT JOIN listino_master lc ON lp.prodotto_id = lc.sku_interno AND lp.fornitore_id = lc.fornitore_id
    WHERE COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag) IS NOT NULL
      AND lp.prezzo_medio > COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)
      AND (((lp.prezzo_medio - COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) / COALESCE(lc.prezzo_pattuito, lp.prezzo_precedente_lag)) * 100) >= :soglia
    ORDER BY lp.mese DESC
    """
    params = {
        "location_id": location_id,
        "anno": anno,
        "soglia": soglia,
    }
    
    res = await db.execute(text(sql), params)
    
    # Crea Workbook excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report Rincari"
    
    ws.views.sheetView[0].showGridLines = True
    
    headers = [
        "Mese", "SKU Interno", "Prodotto", "Fornitore", 
        "Prezzo Target (€)", "Prezzo Medio Rilevato (€)", 
        "Quantità Acquistata", "Rincaro Unitario (€)", "Spreco Rilevato (€)"
    ]
    
    ws.append(headers)
    
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )
    
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border
    
    # Aggiungi i dati
    row_num = 2
    for r in res.all():
        prezzo_medio = float(r.prezzo_medio)
        prezzo_precedente = float(r.prezzo_precedente)
        rincaro_unitario = prezzo_medio - prezzo_precedente
        quantita = float(r.qta_mese_corrente)
        spreco = rincaro_unitario * quantita
        
        row_data = [
            r.mese,
            r.sku_interno,
            r.nome_normalizzato,
            r.fornitore_ragione_sociale,
            prezzo_precedente,
            prezzo_medio,
            quantita,
            rincaro_unitario,
            spreco
        ]
        ws.append(row_data)
        
        for col_idx in range(1, len(row_data) + 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.border = thin_border
            cell.font = Font(name="Calibri", size=11)
            
            if col_idx in (5, 6, 8, 9):
                cell.number_format = '€ #,##0.00'
                cell.alignment = Alignment(horizontal="right")
            elif col_idx == 7:
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="left")
                
        row_num += 1
        
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or '')
            if cell.column in (5, 6, 8, 9) and type(cell.value) in (int, float):
                val_str = f"€ {cell.value:.2f}"
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="dossier_contestazione_rincari.xlsx"'
    }
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )

