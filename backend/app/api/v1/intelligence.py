"""
Price Sentinel — Intelligence Router (Sprint 4).
Espone gli endpoint per la Dashboard Admin, KPI e Cross-Location Tracker.
"""

from datetime import date, timedelta, datetime, timezone
from typing import Any
from io import BytesIO

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func, and_, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_admin, get_current_user
from app.config import settings
from app.database import get_db
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione, ApprovazionePrezzo
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.location import Location
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from fastapi.responses import Response, StreamingResponse
from app.services.pdf_generator import generate_vendor_passport_pdf, generate_consumption_invoices_pdf
from app.schemas.approvazioni import ApprovazionePrezzoCreate, ApprovazionePrezzoResponse
from app.services.anomaly_policy import operational_anomaly_filter

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
    tenant_id = getattr(_admin, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Tenant amministratore non configurato")

    # Tenant ownership belongs to Fattura, not Anomalia. Follow the
    # anomaly -> invoice row -> invoice relation for a scoped aggregate.
    anomalie_stmt = (
        select(
            func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.in_reclamo, Anomalia.delta_totale), else_=0)), 0).label("in_contestazione"),
            func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.contestata, Anomalia.delta_totale), else_=0)), 0).label("a_rischio"),
            func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.da_verificare, Anomalia.delta_totale), else_=0)), 0).label("attesa_manager"),
        )
        .select_from(Anomalia)
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(Fattura.tenant_id == tenant_id)
        .where(operational_anomaly_filter())
    )

    anomalie_res = await db.execute(anomalie_stmt)
    anomalie_row = anomalie_res.one()

    # Credit note ownership is inherited via NotaDiCredito -> Anomalia
    # -> RigaFattura -> Fattura. Never filter nonexistent tenant columns.
    recup_stmt = (
        select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
        .select_from(NotaDiCredito)
        .join(Anomalia, NotaDiCredito.anomalia_id == Anomalia.id)
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(Fattura.tenant_id == tenant_id)
    )
    recuperati_res = await db.execute(recup_stmt)
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
                # Finisce il giorno prima del nuovo: un solo prezzo valido per giorno.
                from app.services.variant_price_import import previous_price_end
                listino_active.data_scadenza = previous_price_end(
                    listino_active.data_inizio_validita, date.today()
                )
                
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


def _parse_date(value: str | None) -> date | None:
    # Called as a plain function the FastAPI Query() default arrives here: treat it as missing.
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_ids(value: str | None) -> list[int] | None:
    if not isinstance(value, str) or not value:
        return None
    ids = [int(part.strip()) for part in value.split(",") if part.strip().isdigit()]
    return ids or None


@router.get("/price-trend/{sku_interno}", summary="Trend Storico Prezzi per SKU")
async def get_price_trend(
    sku_interno: str,
    fornitore_id: int | None = Query(None, description="Solo le righe di questo fornitore"),
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.esclusi import SKUEscluso
    from app.services.price_trend import load_price_trends

    chk = await db.execute(
        select(SKUEscluso.sku_interno).where(
            func.lower(func.trim(SKUEscluso.sku_interno)) == sku_interno.lower().strip()
        )
    )
    if chk.scalars().first():
        raise HTTPException(status_code=400, detail="Prodotto escluso dalle analisi")

    trends_map = await load_price_trends(
        db, _user, [sku_interno], fornitore_ids=[fornitore_id] if isinstance(fornitore_id, int) else None
    )
    return trends_map.get(sku_interno) or {
        "sku_interno": sku_interno,
        "prodotto_nome": sku_interno,
        "prezzo_contratto_corrente": None,
        "unita_contratto_corrente": None,
        "fornitori": [],
        "history": [],
    }


@router.get("/price-trends", summary="Trend Storico Prezzi per SKU multipli")
async def get_price_trends(
    skus: str = Query(..., description="Elenco di SKU separati da virgola"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    location_ids: str | None = Query(None),
    fornitore_ids: str | None = Query(None),
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trend per SKU: solo le righe di quello SKU, prezzo nell'unità del listino del fornitore.

    Ogni punto ha prezzo_fattura/unita_fattura (come in fattura), prezzo_pagato/
    unita_confronto (convertito, None se la conversione non è affidabile),
    prezzo_contratto (listino dello stesso fornitore valido alla data) e is_reso
    per le note di credito. prezzo_contratto_corrente è valorizzato solo quando
    la serie ha un fornitore solo; i contratti per fornitore sono in "fornitori".
    """
    from app.services.price_trend import load_price_trends

    sku_list = [s.strip() for s in skus.split(",") if s.strip()]
    return await load_price_trends(
        db,
        _user,
        sku_list,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
        location_ids=_parse_ids(location_ids),
        fornitore_ids=_parse_ids(fornitore_ids),
    )


# ─────────────────────────────────────────────
# 3. Classifica Efficienza Locali
# ─────────────────────────────────────────────

@router.get("/efficiency-leaderboard", summary="Classifica Efficienza Locali")
async def get_efficiency_leaderboard(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = getattr(_admin, "tenant_id", 1) or 1
    sql = """
    WITH hist_min AS (
        SELECT 
            rf.sku_interno,
            MIN(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0)) as hist_prezzo_min
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        WHERE rf.sku_interno IS NOT NULL
          AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
          AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0
          AND rf.is_omaggio IS NOT TRUE
          AND rf.id NOT IN (SELECT riga_fattura_id FROM righe_escluse_statistiche)
          AND f.tenant_id = :tenant_id
        GROUP BY rf.sku_interno
    ),
    purchases AS (
        SELECT 
            f.location_id,
            COALESCE(loc.nome_struttura, 'Sede Non Assegnata') as nome_struttura,
            rf.id as riga_id,
            COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) as price,
            hm.hist_prezzo_min,
            CASE WHEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) <= (hm.hist_prezzo_min * 1.05) THEN 1 ELSE 0 END as is_optimal
        FROM righe_fattura rf
        JOIN hist_min hm ON rf.sku_interno = hm.sku_interno
        JOIN fatture f ON rf.fattura_id = f.id
        LEFT JOIN location loc ON f.location_id = loc.id
        WHERE rf.sku_interno IS NOT NULL
          AND f.tenant_id = :tenant_id
          AND rf.is_omaggio IS NOT TRUE
          AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0
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
    res = await db.execute(text(sql), {"tenant_id": tenant_id})
    
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


@router.get("/variance-loss", summary="Analisi Sprechi per Mancata Ottimizzazione")
async def get_variance_loss(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Calcola lo spreco finanziario (variance loss) causato dagli acquisti effettuati a un prezzo 
    superiore al prezzo minimo storico registrato per ciascun articolo standard (SKU).
    """
    sql = """
    WITH min_prices AS (
        SELECT 
            sku_interno, 
            MIN(COALESCE(NULLIF(prezzo_netto_normalizzato, 0), prezzo_unitario_fatturato, 0)) AS min_price
        FROM righe_fattura
        WHERE sku_interno IS NOT NULL 
          AND COALESCE(NULLIF(prezzo_netto_normalizzato, 0), prezzo_unitario_fatturato, 0) > 0
          AND sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
          AND is_omaggio IS NOT TRUE
          AND id NOT IN (SELECT riga_fattura_id FROM righe_escluse_statistiche)
        GROUP BY sku_interno
    )
    SELECT 
        r.sku_interno,
        -- One SKU can have an active price list per supplier: read the name with a
        -- subquery, because a join would multiply every invoice line in the totals.
        COALESCE(
            (SELECT MAX(lm.descrizione) FROM listino_master lm WHERE lm.sku_interno = r.sku_interno AND lm.data_scadenza IS NULL),
            MAX(r.descrizione_fornitore_raw),
            r.sku_interno
        ) AS prodotto_nome,
        COALESCE(MAX(f.nome_azienda), 'ND') AS fornitore_nome,
        COUNT(r.id) AS numero_acquisti,
        SUM(r.quantita) AS quantita_totale,
        mp.min_price AS prezzo_minimo,
        AVG(COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0)) AS prezzo_medio,
        SUM(GREATEST(0, COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0) - mp.min_price) * r.quantita) AS spreco_totale
    FROM righe_fattura r
    JOIN min_prices mp ON r.sku_interno = mp.sku_interno
    LEFT JOIN fatture ft ON r.fattura_id = ft.id
    LEFT JOIN fornitori f ON ft.fornitore_id = f.id
    WHERE r.sku_interno IS NOT NULL
      AND r.is_omaggio IS NOT TRUE
      -- Waste counts only purchases uploaded since the price check restarted;
      -- the reference minimum still comes from the whole history.
      AND (CAST(:check_start AS TIMESTAMPTZ) IS NULL OR ft.xml_raw_id IN (SELECT id FROM xml_raw WHERE data_ricezione >= CAST(:check_start AS TIMESTAMPTZ)))
    GROUP BY r.sku_interno, mp.min_price
    HAVING SUM(GREATEST(0, COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0) - mp.min_price) * r.quantita) > 0
    ORDER BY spreco_totale DESC
    LIMIT 10;
    """
    res = await db.execute(text(sql), {"check_start": settings.ANOMALY_CHECK_START})
    
    results = []
    for r in res.all():
        results.append({
            "sku_interno": r.sku_interno,
            "prodotto_nome": r.prodotto_nome,
            "fornitore_nome": r.fornitore_nome,
            "numero_acquisti": int(r.numero_acquisti or 0),
            "quantita_totale": float(r.quantita_totale or 0),
            "prezzo_minimo": float(r.prezzo_minimo or 0),
            "prezzo_medio": float(r.prezzo_medio or 0),
            "spreco_totale": float(r.spreco_totale or 0)
        })
    return results


# ─────────────────────────────────────────────
# 4. Esporta Excel di Contestazione (openpyxl)
# ─────────────────────────────────────────────

@router.get("/export-dispute-excel", summary="Esporta dossier Excel di contestazione")
async def export_dispute_excel(
    location_id: int | None = Query(None),
    anno: int | None = Query(None, ge=2000, le=2100),
    stato: str = Query(StatoValidazione.da_verificare.value, description="Stato delle anomalie (default: quelle da verificare)"),
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dossier dei rincari ricavato dalle anomalie visibili nella ValidationRoom.

    Una riga per anomalia, con prezzi e quantità nell'unità del listino valido
    alla data della fattura: il totale è SUM(delta_totale) delle stesse anomalie
    che l'utente vede (stessi filtri di GET /anomalie, sede compresa per i manager).
    """
    from app.services.dispute_dossier import build_dossier_workbook, load_dossier_rows

    try:
        stato_value = StatoValidazione(stato)
    except ValueError:
        raise HTTPException(status_code=422, detail="Stato anomalia non valido")
    rows = await load_dossier_rows(
        db,
        _user,
        stato=stato_value,
        location_id=location_id if isinstance(location_id, int) else None,
        anno=anno if isinstance(anno, int) else None,
    )
    stream = await run_in_threadpool(build_dossier_workbook, rows)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={'Content-Disposition': 'attachment; filename="dossier_contestazione_rincari.xlsx"'},
    )


# ─────────────────────────────────────────────
# Report Consumi per Prodotto (Product Consumption)
# ─────────────────────────────────────────────

@router.get("/product-consumption", summary="Report Consumo per Prodotto")
async def get_product_consumption(
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Ritorna il report aggregato di consumo per ciascun SKU.
    """
    loc_ids = []
    if location_ids:
        try:
            loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        except ValueError:
            pass

    location_filter = ""
    params = {
        "fornitore_id": fornitore_id,
        "data_da": data_da,
        "data_a": data_a
    }
    if loc_ids:
        id_placeholders = ",".join(f":loc_id_{i}" for i in range(len(loc_ids)))
        location_filter = f"AND f.location_id IN ({id_placeholders})"
        for i, val in enumerate(loc_ids):
            params[f"loc_id_{i}"] = val

    sql = f"""
    WITH product_names AS (
        SELECT
            lower(trim(sku_interno)) AS sku_key,
            MAX(canonical_name) AS canonical_name
        FROM products
        WHERE is_active IS TRUE AND sku_interno IS NOT NULL
        GROUP BY lower(trim(sku_interno))
    )
    SELECT 
        rf.sku_interno, 
        COALESCE(MAX(pn.canonical_name), MAX(rf.descrizione_fornitore_raw)) as descrizione,
        SUM(rf.quantita) as quantita_totale,
        SUM(CASE WHEN rf.is_omaggio = TRUE THEN rf.quantita ELSE 0 END) as quantita_omaggio,
        COALESCE(
            MAX(CASE WHEN rf.is_omaggio = FALSE AND rf.unita_misura_fattura NOT IN ('OMAGGIO', 'omaggio', 'Omaggio') THEN rf.unita_misura_fattura END),
            MAX(rf.unita_misura_fattura)
        ) as unita_misura,
        SUM(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale,
        CASE 
            WHEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END) > 0 
            THEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita ELSE 0 END) / SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END)
            ELSE 0 
        END as prezzo_medio
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    LEFT JOIN product_names pn ON pn.sku_key = lower(trim(rf.sku_interno))
    WHERE rf.sku_interno IS NOT NULL
      AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    GROUP BY rf.sku_interno
    ORDER BY spesa_totale DESC
    """
    
    res = await db.execute(text(sql), params)
    
    results = []
    for r in res.all():
        results.append({
            "sku_interno": r.sku_interno,
            "descrizione": r.descrizione,
            "quantita_totale": float(r.quantita_totale or 0),
            "quantita_omaggio": float(r.quantita_omaggio or 0),
            "unita_misura": r.unita_misura or "Pz",
            "spesa_totale": float(r.spesa_totale or 0),
            "prezzo_medio": float(r.prezzo_medio or 0)
        })
    return results


@router.get("/product-consumption/{sku_interno}", summary="Dettaglio Consumo SKU per Location e Mese")
async def get_product_consumption_detail(
    sku_interno: str,
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.esclusi import SKUEscluso
    chk = await db.execute(select(SKUEscluso).where(SKUEscluso.sku_interno == sku_interno))
    if chk.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Prodotto escluso dalle analisi")

    # Normalizza i parametri in caso di chiamata diretta in Python (es. unit tests)
    if not isinstance(location_ids, str):
        location_ids = None
    if not isinstance(fornitore_id, int):
        fornitore_id = None
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    skus = [x.strip() for x in sku_interno.split(",") if x.strip()]
    if not skus:
        return {
            "sku_interno": sku_interno,
            "consumo_per_location": [],
            "consumo_per_mese": []
        }

    loc_ids = []
    if location_ids:
        try:
            loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        except ValueError:
            pass

    location_filter = ""
    params = {
        "fornitore_id": fornitore_id,
        "data_da": data_da,
        "data_a": data_a
    }
    
    # Costruiamo il filtro SKU dinamico con bind variables
    sku_placeholders = ",".join(f":sku_{i}" for i in range(len(skus)))
    sku_filter = f"rf.sku_interno IN ({sku_placeholders})"
    for i, s in enumerate(skus):
        params[f"sku_{i}"] = s

    if loc_ids:
        id_placeholders = ",".join(f":loc_id_{i}" for i in range(len(loc_ids)))
        location_filter = f"AND f.location_id IN ({id_placeholders})"
        for i, val in enumerate(loc_ids):
            params[f"loc_id_{i}"] = val

    # 1. Split by Location
    sql_loc = f"""
    SELECT 
        COALESCE(l.nome_struttura, 'Sede non assegnata') as location_nome,
        SUM(rf.quantita) as quantita_totale,
        SUM(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    LEFT JOIN location l ON f.location_id = l.id
    WHERE {sku_filter}
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    GROUP BY COALESCE(l.nome_struttura, 'Sede non assegnata')
    ORDER BY spesa_totale DESC
    """
    res_loc = await db.execute(text(sql_loc), params)
    by_location = []
    for r in res_loc.all():
        by_location.append({
            "location_nome": r.location_nome,
            "quantita_totale": float(r.quantita_totale or 0),
            "spesa_totale": float(r.spesa_totale or 0)
        })

    # 2. Split by Month
    sql_month = f"""
    SELECT 
        to_char(f.data_documento, 'YYYY-MM') as mese,
        SUM(rf.quantita) as quantita_totale,
        SUM(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    WHERE {sku_filter}
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    GROUP BY to_char(f.data_documento, 'YYYY-MM')
    ORDER BY mese DESC
    """
    res_month = await db.execute(text(sql_month), params)
    by_month = []
    for r in res_month.all():
        by_month.append({
            "mese": r.mese,
            "quantita_totale": float(r.quantita_totale or 0),
            "spesa_totale": float(r.spesa_totale or 0)
        })

    # 3. Aggregated Prices (Min, Max, Avg)
    sql_prices = f"""
    SELECT 
        MIN(CASE WHEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) END) as prezzo_minimo,
        MAX(CASE WHEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) END) as prezzo_massimo,
        CASE 
            WHEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END) > 0 
            THEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita ELSE 0 END) / SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END)
            ELSE 0 
        END as prezzo_medio
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    WHERE {sku_filter}
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    """
    res_prices = await db.execute(text(sql_prices), params)
    row_prices = res_prices.one_or_none()
    prezzo_minimo = float(row_prices.prezzo_minimo or 0) if row_prices and row_prices.prezzo_minimo else 0.0
    prezzo_massimo = float(row_prices.prezzo_massimo or 0) if row_prices and row_prices.prezzo_massimo else 0.0
    prezzo_medio = float(row_prices.prezzo_medio or 0) if row_prices and row_prices.prezzo_medio else 0.0

    return {
        "sku_interno": sku_interno,
        "consumo_per_location": by_location,
        "consumo_per_mese": by_month,
        "prezzo_minimo": prezzo_minimo,
        "prezzo_massimo": prezzo_massimo,
        "prezzo_medio": prezzo_medio
    }


@router.get("/product-consumption/{sku_interno}/invoices", summary="Dettaglio Fatture che generano il Consumo dello SKU")
async def get_product_consumption_invoices(
    sku_interno: str,
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.esclusi import SKUEscluso
    chk = await db.execute(select(SKUEscluso).where(SKUEscluso.sku_interno == sku_interno))
    if chk.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Prodotto escluso dalle analisi")

    if not isinstance(location_ids, str):
        location_ids = None
    if not isinstance(fornitore_id, int):
        fornitore_id = None
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    skus = [x.strip() for x in sku_interno.split(",") if x.strip()]
    if not skus:
        return []

    loc_ids = []
    if location_ids:
        try:
            loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        except ValueError:
            pass

    location_filter = ""
    params = {
        "fornitore_id": fornitore_id,
        "data_da": data_da,
        "data_a": data_a
    }
    
    sku_placeholders = ",".join(f":sku_{i}" for i in range(len(skus)))
    sku_filter = f"rf.sku_interno IN ({sku_placeholders})"
    for i, s in enumerate(skus):
        params[f"sku_{i}"] = s

    if loc_ids:
        id_placeholders = ",".join(f":loc_id_{i}" for i in range(len(loc_ids)))
        location_filter = f"AND f.location_id IN ({id_placeholders})"
        for i, val in enumerate(loc_ids):
            params[f"loc_id_{i}"] = val

    sql = f"""
    SELECT 
        f.id as fattura_id,
        f.numero_documento,
        f.data_documento,
        COALESCE(l.nome_struttura, 'Sede non assegnata') as location_nome,
        COALESCE(fo.nome_azienda, 'Fornitore non specificato') as fornitore_nome,
        rf.descrizione_fornitore_raw as prodotto_descrizione,
        rf.quantita as quantita,
        rf.unita_misura_fattura as unita_misura,
        COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) as prezzo_unitario,
        (COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale,
        rf.is_omaggio as is_omaggio,
        rf.sku_interno as sku_interno
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    LEFT JOIN location l ON f.location_id = l.id
    LEFT JOIN fornitori fo ON f.fornitore_id = fo.id
    WHERE {sku_filter}
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    ORDER BY f.data_documento DESC, f.numero_documento DESC
    """
    
    res = await db.execute(text(sql), params)
    results = []
    for r in res.all():
        results.append({
            "fattura_id": r.fattura_id,
            "numero_documento": r.numero_documento,
            "data_documento": r.data_documento.isoformat() if r.data_documento else None,
            "location_nome": r.location_nome,
            "fornitore_nome": r.fornitore_nome,
            "prodotto_descrizione": r.prodotto_descrizione,
            "quantita": float(r.quantita or 0),
            "unita_misura": r.unita_misura or "Pz",
            "prezzo_unitario": float(r.prezzo_unitario or 0),
            "spesa_totale": float(r.spesa_totale or 0),
            "is_omaggio": bool(r.is_omaggio or False),
            "sku_interno": r.sku_interno
        })
    return results


@router.get("/product-consumption/{sku_interno}/invoices-pdf", summary="Genera PDF del Riepilogo Fatture di Consumo dello/degli SKU")
async def get_product_consumption_invoices_pdf(
    sku_interno: str,
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.esclusi import SKUEscluso
    chk = await db.execute(select(SKUEscluso).where(SKUEscluso.sku_interno == sku_interno))
    if chk.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Prodotto escluso dalle analisi")

    if not isinstance(location_ids, str):
        location_ids = None
    if not isinstance(fornitore_id, int):
        fornitore_id = None
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    # Recupera i dati delle fatture
    invoices = await get_product_consumption_invoices(
        sku_interno=sku_interno,
        location_ids=location_ids,
        fornitore_id=fornitore_id,
        data_da=data_da,
        data_a=data_a,
        _admin=_admin,
        db=db
    )

    # Determina il titolo del report
    skus = [x.strip() for x in sku_interno.split(",") if x.strip()]
    
    title = sku_interno
    if len(skus) == 1:
        sql_desc = "SELECT descrizione_fornitore_raw FROM righe_fattura WHERE sku_interno = :sku LIMIT 1"
        res_desc = await db.execute(text(sql_desc), {"sku": skus[0]})
        row_desc = res_desc.first()
        if row_desc and row_desc[0]:
            title = f"{skus[0]} - {row_desc[0]}"
    else:
        title = f"Consolidato di {len(skus)} articoli ({', '.join(skus[:3])}{'...' if len(skus) > 3 else ''})"

    # Costruiamo una descrizione dei filtri
    filters_parts = []
    if location_ids:
        loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        if loc_ids:
            res_locs = await db.execute(text("SELECT nome_struttura FROM location WHERE id = ANY(:ids)"), {"ids": list(loc_ids)})
            names = [r[0] for r in res_locs.all()]
            filters_parts.append(f"Sedi: {', '.join(names)}")
    if fornitore_id:
        res_forn = await db.execute(text("SELECT nome_azienda FROM fornitori WHERE id = :fid"), {"fid": fornitore_id})
        row_forn = res_forn.first()
        if row_forn:
            filters_parts.append(f"Fornitore: {row_forn[0]}")
    if data_da:
        filters_parts.append(f"Da: {data_da.strftime('%d/%m/%Y')}")
    if data_a:
        filters_parts.append(f"A: {data_a.strftime('%d/%m/%Y')}")

    filter_desc = " | ".join(filters_parts) if filters_parts else "Nessuno"

    pdf_bytes = await run_in_threadpool(generate_consumption_invoices_pdf, title, invoices, filter_desc)
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=Riepilogo_Fatture_Consumo.pdf"
        }
    )


@router.get("/export-product-consumption-excel", summary="Esporta Excel Consumo per Prodotto")
async def export_product_consumption_excel(
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera ed esporta un report Excel (.xlsx) dei consumi per prodotto.
    """
    loc_ids = []
    if location_ids:
        try:
            loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        except ValueError:
            pass

    location_filter = ""
    params = {
        "fornitore_id": fornitore_id,
        "data_da": data_da,
        "data_a": data_a
    }
    if loc_ids:
        id_placeholders = ",".join(f":loc_id_{i}" for i in range(len(loc_ids)))
        location_filter = f"AND f.location_id IN ({id_placeholders})"
        for i, val in enumerate(loc_ids):
            params[f"loc_id_{i}"] = val

    sql = f"""
    WITH product_names AS (
        SELECT
            lower(trim(sku_interno)) AS sku_key,
            MAX(canonical_name) AS canonical_name
        FROM products
        WHERE is_active IS TRUE AND sku_interno IS NOT NULL
        GROUP BY lower(trim(sku_interno))
    )
    SELECT 
        rf.sku_interno, 
        COALESCE(MAX(pn.canonical_name), MAX(rf.descrizione_fornitore_raw)) as descrizione,
        COALESCE(string_agg(DISTINCT fo.nome_azienda, ', '), 'ND') as fornitori,
        SUM(rf.quantita) as quantita_totale,
        SUM(CASE WHEN rf.is_omaggio = TRUE THEN rf.quantita ELSE 0 END) as quantita_omaggio,
        COALESCE(
            MAX(CASE WHEN rf.is_omaggio = FALSE AND rf.unita_misura_fattura NOT IN ('OMAGGIO', 'omaggio', 'Omaggio') THEN rf.unita_misura_fattura END),
            MAX(rf.unita_misura_fattura)
        ) as unita_misura,
        SUM(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale,
        CASE 
            WHEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END) > 0 
            THEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita ELSE 0 END) / SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END)
            ELSE 0 
        END as prezzo_medio
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    LEFT JOIN product_names pn ON pn.sku_key = lower(trim(rf.sku_interno))
    LEFT JOIN fornitori fo ON f.fornitore_id = fo.id
    WHERE rf.sku_interno IS NOT NULL
      {location_filter}
      AND (cast(:fornitore_id as integer) IS NULL OR f.fornitore_id = cast(:fornitore_id as integer))
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    GROUP BY rf.sku_interno
    ORDER BY spesa_totale DESC
    """
    
    res = await db.execute(text(sql), params)
    
    def _build_workbook(rows):
        # Crea Workbook excel
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Consumi per Prodotto"
    
        # Mostra griglia
        ws.views.sheetView[0].showGridLines = True
    
        headers = [
            "SKU Interno", "Prodotto", "Fornitore", "Quantità Totale", "di cui Omaggi",
            "Unità di Misura", "Prezzo Medio (€)", "Spesa Totale (€)"
        ]
    
        ws.append(headers)
    
        # Stile intestazione elegante (Tonalità Navy coordinata a Price Sentinel)
        header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
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
        for r in rows:
            quantita = float(r.quantita_totale or 0)
            quantita_omaggio = float(r.quantita_omaggio or 0)
            prezzo_medio = float(r.prezzo_medio or 0)
            spesa_totale = float(r.spesa_totale or 0)
        
            row_data = [
                r.sku_interno,
                r.descrizione,
                r.fornitori or "—",
                quantita,
                quantita_omaggio,
                r.unita_misura or "Pz",
                prezzo_medio,
                spesa_totale
            ]
            ws.append(row_data)
        
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_num, column=col_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=11)
            
                if col_idx in (7, 8):
                    cell.number_format = '€ #,##0.00'
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (4, 5):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (1, 6):
                    cell.alignment = Alignment(horizontal="center")
                else:
                    cell.alignment = Alignment(horizontal="left")
                
            row_num += 1
        
        # Auto-fit colonne
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or '')
                if cell.column in (7, 8) and type(cell.value) in (int, float):
                    val_str = f"€ {cell.value:.2f}"
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        
        stream = BytesIO()
        wb.save(stream)
        stream.seek(0)
        return stream

    stream = await run_in_threadpool(_build_workbook, res.all())
    
    headers = {
        'Content-Disposition': 'attachment; filename="report_consumo_prodotti.xlsx"'
    }
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router.get("/top-purchased-products", summary="Ottiene i prodotti più acquistati")
async def get_top_purchased_products(
    limit: int | None = Query(50, ge=1, le=1000),
    sort_by: str = Query("quantita", description="Ordinamento: quantita, spesa, acquisti"),
    fornitore_id: int | None = Query(None, description="ID singolo fornitore (retrocompatibilità)"),
    fornitore_ids: str | None = Query(None, description="ID fornitori separati da virgola per multi-selezione"),
    location_ids: str | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Ritorna la lista dei prodotti più acquistati filtrati per fornitori, location e date range.
    """
    loc_ids = []
    if location_ids:
        try:
            loc_ids = [int(x) for x in location_ids.split(",") if x.strip()]
        except ValueError:
            pass

    forn_ids = []
    if fornitore_ids:
        try:
            forn_ids = [int(x) for x in fornitore_ids.split(",") if x.strip()]
        except ValueError:
            pass
    elif fornitore_id is not None:
        forn_ids = [fornitore_id]

    location_filter = ""
    fornitore_filter = ""
    params = {
        "data_da": data_da,
        "data_a": data_a,
        "limit": limit
    }

    if loc_ids:
        id_placeholders = ",".join(f":loc_id_{i}" for i in range(len(loc_ids)))
        location_filter = f"AND f.location_id IN ({id_placeholders})"
        for i, val in enumerate(loc_ids):
            params[f"loc_id_{i}"] = val

    if forn_ids:
        forn_placeholders = ",".join(f":forn_id_{i}" for i in range(len(forn_ids)))
        fornitore_filter = f"AND f.fornitore_id IN ({forn_placeholders})"
        for i, val in enumerate(forn_ids):
            params[f"forn_id_{i}"] = val

    valid_sorts = {
        "quantita": "quantita_totale DESC",
        "spesa": "spesa_totale DESC",
        "acquisti": "numero_acquisti DESC"
    }
    order_by_clause = valid_sorts.get(sort_by, "quantita_totale DESC")

    sql = f"""
    SELECT 
        rf.sku_interno, 
        MAX(rf.descrizione_fornitore_raw) as descrizione,
        COALESCE(string_agg(DISTINCT fo.nome_azienda, ', '), '—') as fornitori,
        SUM(rf.quantita) as quantita_totale,
        SUM(CASE WHEN rf.is_omaggio = TRUE THEN rf.quantita ELSE 0 END) as quantita_omaggio,
        COALESCE(
            MAX(CASE WHEN rf.is_omaggio = FALSE AND rf.unita_misura_fattura NOT IN ('OMAGGIO', 'omaggio', 'Omaggio') THEN rf.unita_misura_fattura END),
            MAX(rf.unita_misura_fattura)
        ) as unita_misura,
        SUM(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita) as spesa_totale,
        COUNT(rf.id) as numero_acquisti,
        CASE 
            WHEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END) > 0 
            THEN SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) * rf.quantita ELSE 0 END) / SUM(CASE WHEN rf.is_omaggio = FALSE AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0 THEN rf.quantita ELSE 0 END)
            ELSE 0 
        END as prezzo_medio
    FROM righe_fattura rf
    JOIN fatture f ON rf.fattura_id = f.id
    LEFT JOIN fornitori fo ON f.fornitore_id = fo.id
    WHERE rf.sku_interno IS NOT NULL
      AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
      {location_filter}
      {fornitore_filter}
      AND (cast(:data_da as date) IS NULL OR f.data_documento >= cast(:data_da as date))
      AND (cast(:data_a as date) IS NULL OR f.data_documento <= cast(:data_a as date))
    GROUP BY rf.sku_interno
    ORDER BY {order_by_clause}
    LIMIT :limit
    """
    
    res = await db.execute(text(sql), params)
    
    results = []
    for r in res.all():
        results.append({
            "sku_interno": r.sku_interno,
            "descrizione": r.descrizione,
            "fornitori": r.fornitori or "—",
            "quantita_totale": float(r.quantita_totale or 0),
            "quantita_omaggio": float(r.quantita_omaggio or 0),
            "unita_misura": r.unita_misura or "Pz",
            "spesa_totale": float(r.spesa_totale or 0),
            "numero_acquisti": int(r.numero_acquisti or 0),
            "prezzo_medio": float(r.prezzo_medio or 0)
        })
    return results


@router.get("/export-top-purchased-excel", summary="Esporta Excel dei prodotti più acquistati")
async def export_top_purchased_excel(
    limit: int | None = Query(50, ge=1, le=1000),
    sort_by: str = Query("quantita", description="Ordinamento: quantita, spesa, acquisti"),
    fornitore_id: int | None = Query(None),
    fornitore_ids: str | None = Query(None),
    location_ids: str | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Genera ed esporta un report Excel (.xlsx) dei prodotti più acquistati con filtri.
    """
    data = await get_top_purchased_products(
        limit=limit,
        sort_by=sort_by,
        fornitore_id=fornitore_id,
        fornitore_ids=fornitore_ids,
        location_ids=location_ids,
        data_da=data_da,
        data_a=data_a,
        _admin=_admin,
        db=db
    )
    
    def _build_workbook(data):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Listino Top Prodotti"
    
        ws.views.sheetView[0].showGridLines = True
    
        headers = [
            "Posizione", "SKU Interno", "Prodotto", "Fornitore", "Unità di Misura", 
            "Quantità Totale", "Numero Acquisti", "Prezzo Medio (€)", "Spesa Totale (€)"
        ]
    
        ws.append(headers)
    
        header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
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
    
        row_num = 2
        for idx, item in enumerate(data):
            row_data = [
                idx + 1,
                item["sku_interno"],
                item["descrizione"],
                item["fornitori"],
                item["unita_misura"],
                item["quantita_totale"],
                item["numero_acquisti"],
                item["prezzo_medio"],
                item["spesa_totale"]
            ]
            ws.append(row_data)
        
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_num, column=col_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=11)
            
                if col_idx in (8, 9):
                    cell.number_format = '€ #,##0.00'
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx == 6:
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx == 7:
                    cell.number_format = '#,##0'
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx in (1, 2, 5):
                    cell.alignment = Alignment(horizontal="center")
                else:
                    cell.alignment = Alignment(horizontal="left")
                
            row_num += 1
        
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or '')
                if cell.column in (8, 9) and type(cell.value) in (int, float):
                    val_str = f"€ {cell.value:.2f}"
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        
        stream = BytesIO()
        wb.save(stream)
        stream.seek(0)
        return stream

    stream = await run_in_threadpool(_build_workbook, data)
    
    filename = f"listino_top_{limit or 'all'}_prodotti.xlsx"
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router.post("/auto-catalog-initialize", summary="Inizializza automaticamente il catalogo dai dati delle fatture")
async def auto_catalog_initialize(
    fornitore_id: int | None = Query(None, description="ID del fornitore da inizializzare (opzionale)"),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Rileva le righe in parking e senza SKU per il fornitore indicato (o per tutti i fornitori),
    genera automaticamente gli SKU interni basandosi sulla descrizione o codice,
    popola il listino master e la tabella alias, e infine associa tutte le righe di fattura.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Auto-associazione SKU disattivata: usa Prodotti fuori listino per "
            "approvare le associazioni o creare nuovi prodotti in modo controllato."
        ),
    )

    from decimal import Decimal
    import re
    from sqlalchemy import update
    from app.models.alias import AliasProdotto
    from app.models.utenti import Utente
    from app.models.listino import ListinoMaster
    
    # 1. Trova i fornitori da elaborare
    if fornitore_id is not None:
        suppliers_res = await db.execute(
            select(Fornitore.id, Fornitore.nome_azienda).where(Fornitore.id == fornitore_id)
        )
    else:
        # Trova tutti i fornitori che hanno almeno una riga fattura in parking/senza SKU e non omaggio
        suppliers_res = await db.execute(
            select(Fornitore.id, Fornitore.nome_azienda)
            .join(Fattura, Fattura.fornitore_id == Fornitore.id)
            .join(RigaFattura, RigaFattura.fattura_id == Fattura.id)
            .where(and_(RigaFattura.sku_interno.is_(None), RigaFattura.is_omaggio.isnot(True)))
            .distinct()
        )
    
    suppliers = suppliers_res.all()
    if not suppliers:
        return {
            "status": "no_work",
            "message": "Tutti i fornitori sono già inizializzati o non ci sono righe fattura senza SKU."
        }
    
    # Trova admin_id per l'audit trail delle conferme alias
    admin_res = await db.execute(select(Utente.id).where(Utente.ruolo == 'admin').limit(1))
    admin_id = admin_res.scalar() or 1
    
    report = []
    
    for forn_id, forn_nome in suppliers:
        # Recupera tutte le righe non associate per questo fornitore
        rows_res = await db.execute(
            select(
                RigaFattura.id,
                RigaFattura.codice_fornitore_raw,
                RigaFattura.descrizione_fornitore_raw,
                RigaFattura.prezzo_unitario_fatturato,
                RigaFattura.unita_misura_fattura
            )
            .join(Fattura, RigaFattura.fattura_id == Fattura.id)
            .where(and_(
                Fattura.fornitore_id == forn_id,
                RigaFattura.sku_interno.is_(None),
                RigaFattura.is_omaggio.isnot(True)
            ))
        )
        all_rows = rows_res.all()
        if not all_rows:
            continue
            
        # Raggruppa per descrizione fornitore
        product_groups = {}
        for r_id, code_raw, desc_raw, price_fat, uom_fat in all_rows:
            desc = desc_raw
            if not desc:
                continue
            if desc not in product_groups:
                product_groups[desc] = {
                    "codes": set(),
                    "prices": [],
                    "uoms": set(),
                    "row_ids": []
                }
            if code_raw and code_raw != 'None':
                product_groups[desc]["codes"].add(code_raw)
            if uom_fat and uom_fat != 'None':
                product_groups[desc]["uoms"].add(uom_fat)
            product_groups[desc]["prices"].append(Decimal(str(price_fat)))
            product_groups[desc]["row_ids"].append(r_id)
            
        used_skus = set()
        created_listino = 0
        created_alias = 0
        updated_rows = 0
        
        # Genera prefisso SKU basato sul nome azienda del fornitore (es: VEMO_ o NAVAS_)
        clean_prefix = re.sub(r'[^a-zA-Z0-9]+', '', forn_nome).upper()
        prefix = f"{clean_prefix[:5]}_"
        
        for desc, info in product_groups.items():
            code = list(info["codes"])[0] if info["codes"] else None
            prices = [p for p in info["prices"] if p > 0]
            min_price = min(prices) if prices else min(info["prices"]) if info["prices"] else Decimal("0.0")
            uom = list(info["uoms"])[0] if info["uoms"] else "Pz"
            
            sku = None
            if code:
                clean_code = re.sub(r'[^a-zA-Z0-9\-]+', '_', code).upper().strip('_')
                sku = f"{prefix}{clean_code}"
            if not sku:
                clean_desc = re.sub(r'[^a-zA-Z0-9\-]+', '_', desc).upper().strip('_')
                sku = f"{prefix}{clean_desc[:35]}"
                
            base_sku = sku
            counter = 1
            while sku in used_skus:
                sku = f"{base_sku[:40]}_{counter}"
                counter += 1
            used_skus.add(sku)
            
            # 1. Crea record in listino_master (con data di validità pregressa)
            db.add(ListinoMaster(
                fornitore_id=forn_id,
                sku_interno=sku,
                descrizione=desc,
                prezzo_pattuito=min_price,
                unita_misura=uom,
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None
            ))
            created_listino += 1
            
            # 2. Crea record in alias_prodotti
            for c in info["codes"]:
                # Verifica duplicato
                alias_ex_res = await db.execute(
                    select(AliasProdotto.id).where(and_(
                        AliasProdotto.fornitore_id == forn_id,
                        AliasProdotto.codice_fornitore_originale == c
                    ))
                )
                if not alias_ex_res.scalar():
                    db.add(AliasProdotto(
                        fornitore_id=forn_id,
                        codice_fornitore_originale=c,
                        sku_interno=sku,
                        coefficiente_conversione=1.0,
                        confermato_da_user_id=admin_id,
                        created_at=datetime.now(timezone.utc)
                    ))
                    created_alias += 1
                    
            # 3. Aggiorna righe_fattura
            row_ids = info["row_ids"]
            if row_ids:
                await db.execute(
                    update(RigaFattura)
                    .where(RigaFattura.id.in_(row_ids))
                    .values(sku_interno=sku, stato_matching=StatoMatching.matched)
                )
                updated_rows += len(row_ids)
                
        report.append({
            "fornitore_id": forn_id,
            "fornitore_nome": forn_nome,
            "prodotti_creati": created_listino,
            "alias_creati": created_alias,
            "righe_aggiornate": updated_rows
        })
        
    await db.commit()
    return {
        "status": "success",
        "message": f"Inizializzazione completata con successo per {len(report)} fornitori.",
        "report": report
    }

