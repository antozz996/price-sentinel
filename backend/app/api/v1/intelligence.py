"""
Price Sentinel — Intelligence Router (Sprint 4).
Espone gli endpoint per la Dashboard Admin, KPI e Cross-Location Tracker.
"""

from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo
from io import BytesIO

from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
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
from app.models.listino import ORIGINE_APPROVAZIONE_ANOMALIA, ORIGINE_FATTURA, ListinoMaster
from app.models.fornitori import Fornitore
from fastapi.responses import Response, StreamingResponse
from app.services.pdf_generator import generate_consumption_invoices_pdf
from app.schemas.approvazioni import ApprovazionePrezzoCreate, ApprovazionePrezzoResponse
from app.services.anomaly_policy import operational_anomaly_filter
from app.services.anomaly_kpi import kpi_anomalies_statement, kpi_recovered_statement
from app.services import consumption_report, matrix_cache
from app.services.variance_loss import efficiency_leaderboard_select, load_variance_loss

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
    - Euro Recuperati Totali (NC legacy + note registrate nelle pratiche)
    - Euro In Contestazione (Anomalie in_reclamo, al netto del gia' recuperato)
    - Euro A Rischio (Anomalie contestate ma non ancora in reclamo)
    - Euro Attesa Manager (da_verificare)
    Stesso perimetro della lista anomalie: vedi services/anomaly_kpi.py.
    """
    tenant_id = getattr(_admin, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Tenant amministratore non configurato")

    anomalie_row = (await db.execute(kpi_anomalies_statement(_admin))).one()
    recuperati = (await db.execute(kpi_recovered_statement(_admin))).scalar()

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
        # L'approvazione non indica il fornitore: il listino si aggiorna solo se
        # la voce ha UN solo prezzo valido oggi (un fornitore, un'offerta).
        # Prima si prendeva la prima riga aperta di qualunque fornitore e si
        # poteva chiudere il prezzo di un altro; e senza listino si creava un
        # prezzo dal fornitore di una fattura qualsiasi. Ora in quei casi non
        # si tocca il listino.
        from app.services.variant_price_import import previous_price_end, sole_active_price
        today = datetime.now(ZoneInfo("Europe/Rome")).date()
        active_rows = (await db.execute(
            select(ListinoMaster).where(
                ListinoMaster.sku_interno == data.sku_interno,
                ListinoMaster.data_inizio_validita <= today,
                or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= today),
            )
        )).scalars().all()
        listino_active = sole_active_price(active_rows)

        if listino_active is not None and Decimal(str(listino_active.prezzo_pattuito)) != Decimal(str(data.prezzo_approvato)):
            # Append-only: il vecchio finisce il giorno prima del nuovo.
            listino_active.data_scadenza = previous_price_end(listino_active.data_inizio_validita, today)
            db.add(ListinoMaster(
                fornitore_id=listino_active.fornitore_id,
                sku_interno=data.sku_interno,
                descrizione=listino_active.descrizione,
                prezzo_pattuito=data.prezzo_approvato,
                unita_misura=listino_active.unita_misura,
                data_inizio_validita=today,
                data_scadenza=None,
                supplier_product_alias_id=listino_active.supplier_product_alias_id,
                origine=ORIGINE_APPROVAZIONE_ANOMALIA,
            ))
        
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

@matrix_cache.view("efficiency-leaderboard")
def _leaderboard_computer(user):
    async def compute(db: AsyncSession, params: dict):
        return await get_efficiency_leaderboard(_admin=user, db=db)
    return compute


@router.get("/efficiency-leaderboard", summary="Classifica Efficienza Locali")
async def efficiency_leaderboard_endpoint(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """get_efficiency_leaderboard served from services.matrix_cache while the data is unchanged."""
    return await matrix_cache.cached_response(db, _admin, "efficiency-leaderboard")


async def get_efficiency_leaderboard(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Quota di acquisti pagati entro il 5% del minimo per (voce, unità di fattura).

    Base comune services.purchase_lines: tenant, niente note di credito né omaggi,
    righe e voci escluse fuori sia dal minimo sia dal conteggio.
    """
    res = await db.execute(efficiency_leaderboard_select(_admin))

    leaderboard = []
    for i, r in enumerate(res.all()):
        rank = i + 1
        medal = "🏆" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"#{rank}"))
        leaderboard.append({
            "rank": rank,
            "medal": medal,
            "location_id": r.location_id,
            "nome_struttura": r.nome_struttura,
            "totali": int(r.totali or 0),
            "ottimali": int(r.ottimali or 0),
            "score": float(r.score or 0)
        })
    return leaderboard


@matrix_cache.view("variance-loss")
def _variance_loss_computer(user):
    async def compute(db: AsyncSession, params: dict):
        return await get_variance_loss(_admin=user, db=db)
    return compute


@router.get("/variance-loss", summary="Analisi Sprechi per Mancata Ottimizzazione")
async def variance_loss_endpoint(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """get_variance_loss served from services.matrix_cache while the data is unchanged."""
    return await matrix_cache.cached_response(
        db, _admin, "variance-loss", check_start=str(settings.ANOMALY_CHECK_START)
    )


async def get_variance_loss(
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Spreco = acquisti pagati sopra il riferimento: listino del fornitore valido alla
    data della riga se confrontabile, altrimenti il minimo pagato per (voce, unità
    di fattura). Conta le fatture caricate da ANOMALY_CHECK_START (periodo_dal).
    Regole e dettagli in services/variance_loss.py.
    """
    return await load_variance_loss(db, _admin, settings.ANOMALY_CHECK_START)


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
# Report Consumi per Prodotto e Top prodotti
# Un solo calcolo (services/consumption_report.py) per tabella, dettaglio, fatture,
# PDF ed Excel, sulle righe d'acquisto della base comune (purchase_lines).
# ─────────────────────────────────────────────

class ConsumptionSelection(BaseModel):
    """Selezione del dettaglio consumi. Gli SKU viaggiano nel corpo della richiesta:
    con "Seleziona tutto" (1.757 SKU) l'URL superava gli 8 KB accettati da nginx."""

    skus: list[str] = Field(..., min_length=1, max_length=20000)
    location_ids: list[int] | None = None
    fornitore_id: int | None = None
    data_da: date | None = None
    data_a: date | None = None


def _consumption_filters(location_ids=None, fornitore_id=None, data_da=None, data_a=None, skus=None):
    # isinstance: le funzioni sono chiamate anche direttamente (script, test) con i default Query(...).
    return consumption_report.ReportFilters.build(
        location_ids=location_ids,
        fornitore_ids=[fornitore_id] if isinstance(fornitore_id, int) else None,
        date_from=data_da,
        date_to=data_a,
        skus=skus,
    )


async def _consumption_items(db: AsyncSession, user, filters) -> list[dict]:
    """Righe della tabella Consumi (una per SKU): le stesse per schermo, Excel e Top prodotti."""
    rows, conversions = await consumption_report.load_lines(db, user, filters)
    return consumption_report.aggregate_by_sku(rows, conversions)


async def _selected_skus(db: AsyncSession, raw) -> list[str]:
    skus = consumption_report.parse_skus(raw)
    found = await consumption_report.excluded_skus(db, skus)
    if found:
        raise HTTPException(status_code=400, detail=f"Prodotto escluso dalle analisi: {', '.join(sorted(found))}")
    return skus


async def _consumption_detail(db: AsyncSession, user, raw_skus, filters_kwargs: dict) -> dict:
    skus = await _selected_skus(db, raw_skus)
    if not skus:
        return {"sku_interno": "", "numero_prodotti": 0, "consumo_per_location": [], "consumo_per_mese": [],
                "quantita_per_unita": [], "spesa_totale": 0.0, "unita_misura": None, "quantita_totale": None,
                "prezzo_minimo": None, "prezzo_massimo": None, "prezzo_medio": None}
    filters = _consumption_filters(skus=skus, **filters_kwargs)
    rows, conversions = await consumption_report.load_lines(db, user, filters)
    detail = consumption_report.consumption_detail(rows, conversions)
    detail["sku_interno"] = skus[0] if len(skus) == 1 else f"{len(skus)} articoli"
    return detail


async def _consumption_invoices(db: AsyncSession, user, skus: list[str], filters_kwargs: dict):
    if not skus:
        return [], []
    rows, conversions = await consumption_report.load_lines(db, user, _consumption_filters(skus=skus, **filters_kwargs))
    return consumption_report.invoice_rows(rows, conversions), rows


async def _consumption_pdf(db: AsyncSession, user, raw_skus, filters_kwargs: dict) -> Response:
    skus = await _selected_skus(db, raw_skus)
    invoices, rows = await _consumption_invoices(db, user, skus, filters_kwargs)
    title = consumption_report.report_title(skus, rows) if skus else ""

    filters_parts = []
    loc_ids = consumption_report.parse_ids(filters_kwargs.get("location_ids"))
    if loc_ids:
        names = (await db.scalars(select(Location.nome_struttura).where(Location.id.in_(loc_ids)))).all()
        filters_parts.append(f"Sedi: {', '.join(names)}")
    fornitore_id = filters_kwargs.get("fornitore_id")
    if isinstance(fornitore_id, int):
        nome = await db.scalar(select(Fornitore.nome_azienda).where(Fornitore.id == fornitore_id))
        if nome:
            filters_parts.append(f"Fornitore: {nome}")
    data_da, data_a = filters_kwargs.get("data_da"), filters_kwargs.get("data_a")
    if isinstance(data_da, date):
        filters_parts.append(f"Da: {data_da.strftime('%d/%m/%Y')}")
    if isinstance(data_a, date):
        filters_parts.append(f"A: {data_a.strftime('%d/%m/%Y')}")
    filter_desc = " | ".join(filters_parts) if filters_parts else "Nessuno"

    pdf_bytes = await run_in_threadpool(generate_consumption_invoices_pdf, title, invoices, filter_desc)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Riepilogo_Fatture_Consumo.pdf"},
    )


def _selection_filters(selection: ConsumptionSelection) -> dict:
    return {
        "location_ids": selection.location_ids,
        "fornitore_id": selection.fornitore_id,
        "data_da": selection.data_da,
        "data_a": selection.data_a,
    }


@matrix_cache.view("product-consumption")
def _consumption_computer(user):
    async def compute(db: AsyncSession, params: dict):
        return await get_product_consumption(
            location_ids=params["location_ids"], fornitore_id=params["fornitore_id"],
            data_da=date.fromisoformat(params["data_da"]) if params["data_da"] else None,
            data_a=date.fromisoformat(params["data_a"]) if params["data_a"] else None,
            _admin=user, db=db,
        )
    return compute


@router.get("/product-consumption", summary="Report Consumo per Prodotto")
async def product_consumption_endpoint(
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """get_product_consumption served from services.matrix_cache while the data is unchanged."""
    return await matrix_cache.cached_response(
        db, _admin, "product-consumption",
        location_ids=location_ids, fornitore_id=fornitore_id, data_da=data_da, data_a=data_a,
    )


async def get_product_consumption(
    location_ids: str | None = Query(None),
    fornitore_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Una riga per SKU: spesa netta (note di credito sottratte), quantità nell'unità di
    confronto quando la conversione è affidabile, altrimenti divise per unità di fattura.
    """
    return await _consumption_items(db, _admin, _consumption_filters(location_ids, fornitore_id, data_da, data_a))


@router.post("/product-consumption/detail", summary="Dettaglio Consumo di uno o più SKU per Sede e Mese")
async def post_product_consumption_detail(
    selection: ConsumptionSelection,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _consumption_detail(db, _admin, selection.skus, _selection_filters(selection))


@router.post("/product-consumption/invoices", summary="Fatture che generano il Consumo degli SKU selezionati")
async def post_product_consumption_invoices(
    selection: ConsumptionSelection,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    skus = await _selected_skus(db, selection.skus)
    invoices, _ = await _consumption_invoices(db, _admin, skus, _selection_filters(selection))
    return invoices


@router.post("/product-consumption/invoices-pdf", summary="PDF del Riepilogo Fatture di Consumo degli SKU selezionati")
async def post_product_consumption_invoices_pdf(
    selection: ConsumptionSelection,
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _consumption_pdf(db, _admin, selection.skus, _selection_filters(selection))


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
    """Versione GET per pochi SKU (separati da virgola). Per selezioni grandi usare POST /product-consumption/detail."""
    filters = {"location_ids": location_ids, "fornitore_id": fornitore_id, "data_da": data_da, "data_a": data_a}
    return await _consumption_detail(db, _admin, sku_interno, filters)


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
    skus = await _selected_skus(db, sku_interno)
    filters = {"location_ids": location_ids, "fornitore_id": fornitore_id, "data_da": data_da, "data_a": data_a}
    invoices, _ = await _consumption_invoices(db, _admin, skus, filters)
    return invoices


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
    filters = {"location_ids": location_ids, "fornitore_id": fornitore_id, "data_da": data_da, "data_a": data_a}
    return await _consumption_pdf(db, _admin, sku_interno, filters)


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
    Excel dei consumi per prodotto: stesse righe e stessi filtri della tabella a schermo
    (SKU esclusi compresi), con il totale della spesa netta in fondo.
    """
    items = await _consumption_items(db, _admin, _consumption_filters(location_ids, fornitore_id, data_da, data_a))
    rows = consumption_report.consumption_excel_rows(items)
    total = ["TOTALE", f"{len(items)} prodotti", "", "", "", "", "", "", "",
             sum(i["spesa_totale"] for i in items), ""]
    stream = await run_in_threadpool(
        lambda: consumption_report.build_workbook(
            "Consumi per Prodotto", consumption_report.CONSUMPTION_EXCEL_HEADERS, rows,
            money_cols=(9, 10), number_cols=(4, 7, 8), int_cols=(11,), center_cols=(1, 5), total_row=total,
        )
    )
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={'Content-Disposition': 'attachment; filename="report_consumo_prodotti.xlsx"'},
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
    Classifica dei prodotti (stesso calcolo della tabella Consumi) e spesa netta di tutte
    le voci filtrate, indipendente dal limite e dall'ordinamento.
    """
    forn_ids = consumption_report.parse_ids(fornitore_ids)
    if forn_ids is None and isinstance(fornitore_id, int):
        forn_ids = [fornitore_id]
    filters = consumption_report.ReportFilters.build(
        location_ids=location_ids, fornitore_ids=forn_ids, date_from=data_da, date_to=data_a,
    )
    items = await _consumption_items(db, _admin, filters)
    sort_key = sort_by if isinstance(sort_by, str) and sort_by in consumption_report.SORT_KEYS else "quantita"
    return consumption_report.top_products(items, sort_key, limit if isinstance(limit, int) else 50)


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
    Excel dei prodotti più acquistati: le stesse righe della tabella a schermo.
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
    rows = consumption_report.top_excel_rows(data["prodotti"])
    total = ["", "TOTALE", f"Spesa netta di tutte le voci filtrate ({data['numero_prodotti']})", "", "", "", "",
             "", "", "", data["totale_spesa"]]
    stream = await run_in_threadpool(
        lambda: consumption_report.build_workbook(
            "Listino Top Prodotti", consumption_report.TOP_EXCEL_HEADERS, rows,
            money_cols=(10, 11), number_cols=(5, 8), int_cols=(9,), center_cols=(1, 2, 6), total_row=total,
        )
    )
    filename = f"listino_top_{limit if isinstance(limit, int) else 'all'}_prodotti.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
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
                data_scadenza=None,
                origine=ORIGINE_FATTURA,
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

