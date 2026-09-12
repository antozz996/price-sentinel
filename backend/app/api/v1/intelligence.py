"""
Price Sentinel — Intelligence Router (Sprint 4).
Espone gli endpoint per la Dashboard Admin, KPI e Cross-Location Tracker.
"""

from datetime import date, timedelta, datetime, timezone
from typing import Any
from io import BytesIO

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, and_, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, get_current_user
from app.database import get_db
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione, ApprovazionePrezzo
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.location import Location
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from fastapi.responses import Response, StreamingResponse
from app.services.pdf_generator import generate_vendor_passport_pdf, generate_consumption_invoices_pdf
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
    tenant_id = getattr(_admin, "tenant_id", None)

    # Optimized single query for Anomalia states
    anomalie_stmt = select(
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.in_reclamo, Anomalia.delta_totale), else_=0)), 0).label("in_contestazione"),
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.contestata, Anomalia.delta_totale), else_=0)), 0).label("a_rischio"),
        func.coalesce(func.sum(case((Anomalia.stato_validazione == StatoValidazione.da_verificare, Anomalia.delta_totale), else_=0)), 0).label("attesa_manager"),
    )
    if tenant_id:
        anomalie_stmt = anomalie_stmt.where(Anomalia.tenant_id == tenant_id)

    anomalie_res = await db.execute(anomalie_stmt)
    anomalie_row = anomalie_res.one()

    # Recuperati Totali (from NotaDiCredito table)
    recup_stmt = select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
    if tenant_id:
        recup_stmt = recup_stmt.where(NotaDiCredito.tenant_id == tenant_id)
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


@router.get("/cross-location", summary="Cross-Location Tracker")
async def get_cross_location_matrix(
    data_da: date | None = Query(None, description="Data inizio"),
    data_a: date | None = Query(None, description="Data fine"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Matrice di intelligence negoziale.
    Ritorna l'ultimo prezzo di acquisto di uno sku per ogni location.
    I dati permettono al frontend di costruire una griglia Prodotti x Location.
    """
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    # Costruzione condizioni dinamiche per data
    from app.models.esclusi import SKUEscluso
    valid_price = func.coalesce(func.nullif(RigaFattura.prezzo_netto_normalizzato, 0), RigaFattura.prezzo_unitario_fatturato, 0)
    conditions = [
        RigaFattura.sku_interno.isnot(None),
        valid_price > 0,
        RigaFattura.is_omaggio.isnot(True),
        ~RigaFattura.sku_interno.in_(select(SKUEscluso.sku_interno))
    ]
    if data_da:
        conditions.append(Fattura.data_documento >= data_da)
    if data_a:
        conditions.append(Fattura.data_documento <= data_a)

    # Vogliamo l'ultimo prezzo normalizzato per (sku_interno, location_id).
    # Group By SKU e Location, max ID
    subquery = (
        select(
            RigaFattura.sku_interno,
            Fattura.location_id,
            func.max(RigaFattura.id).label("max_riga_id")
        )
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(and_(*conditions))
        .group_by(RigaFattura.sku_interno, Fattura.location_id)
        .subquery()
    )
    
    stmt = (
        select(
            RigaFattura.sku_interno, 
            Fattura.location_id, 
            valid_price.label("prezzo_netto_normalizzato"),
            RigaFattura.descrizione_fornitore_raw,
            Fattura.id.label("fattura_id"),
            RigaFattura.quantita
        )
        .join(subquery, RigaFattura.id == subquery.c.max_riga_id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
    )
    
    res = await db.execute(stmt)
    records = res.all()
    
    # Costruiamo la risposta JSON formattata per la griglia UI
    matrix = {}
    for sku, loc_id, price, desc, fattura_id, quantita in records:
        display_name = f"{desc or 'Prodotto Senza Nome'} ({sku})"
        if display_name not in matrix:
            matrix[display_name] = {}
        # Arrotonda a 2 decimali per allinearsi perfettamente alla griglia UI ed evitare falsi positivi
        matrix[display_name][loc_id] = {
            "prezzo": round(float(price), 2),
            "fattura_id": int(fattura_id),
            "quantita": float(quantita)
        }
        
    # Filtriamo per restituire solo gli SKU con reale delta prezzi tra le sedi (delta > 0.01)
    filtered_matrix = {}
    for display_name, loc_prices in matrix.items():
        prices = [item["prezzo"] for item in loc_prices.values()]
        if len(prices) > 1 and (max(prices) - min(prices)) > 0.011:
            filtered_matrix[display_name] = loc_prices
            
    # Ordiniamo alfabeticamente per nome del prodotto
    sorted_matrix = {k: filtered_matrix[k] for k in sorted(filtered_matrix.keys())}
            
    return sorted_matrix


@router.get("/cross-supplier", summary="Cross-Supplier Pricing Matrix")
async def get_cross_supplier_matrix(
    data_da: date | None = Query(None, description="Data inizio"),
    data_a: date | None = Query(None, description="Data fine"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Ritorna la matrice comparativa incrociata dei prezzi per fornitore.
    Incrocia i listini concordati (ListinoMaster) e le fatture storiche (prezzo spot minimo).
    """
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    # 1. Recupero contratti attivi nel periodo
    contracts_stmt = select(
        ListinoMaster.sku_interno,
        ListinoMaster.descrizione,
        ListinoMaster.fornitore_id,
        ListinoMaster.prezzo_pattuito
    )
    from app.models.esclusi import SKUEscluso
    contracts_conds = [~ListinoMaster.sku_interno.in_(select(SKUEscluso.sku_interno))]
    if data_da:
        contracts_conds.append(or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= data_da))
    if data_a:
        contracts_conds.append(ListinoMaster.data_inizio_validita <= data_a)
        
    contracts_stmt = contracts_stmt.where(and_(*contracts_conds))
    
    contracts_res = await db.execute(contracts_stmt)
    contracts = contracts_res.all()
    
    # 2. Recupero prezzi storici spot minimi da righe fattura registrate
    # Supportiamo fallback prezzo netto normalizzato o unitario
    valid_spot_price = func.coalesce(func.nullif(RigaFattura.prezzo_netto_normalizzato, 0), RigaFattura.prezzo_unitario_fatturato, 0)
    spot_conds = [
        RigaFattura.sku_interno.isnot(None),
        valid_spot_price > 0,
        RigaFattura.is_omaggio.isnot(True),
        ~RigaFattura.sku_interno.in_(select(SKUEscluso.sku_interno))
    ]
    if data_da:
        spot_conds.append(Fattura.data_documento >= data_da)
    if data_a:
        spot_conds.append(Fattura.data_documento <= data_a)

    spot_stmt = (
        select(
            RigaFattura.sku_interno,
            RigaFattura.descrizione_fornitore_raw,
            Fattura.fornitore_id,
            func.min(valid_spot_price).label("prezzo_min")
        )
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(and_(*spot_conds))
        .group_by(RigaFattura.sku_interno, RigaFattura.descrizione_fornitore_raw, Fattura.fornitore_id)
    )
    
    spot_res = await db.execute(spot_stmt)
    spots = spot_res.all()
    
    # 3. Consolidamento dei dati in formato SKU -> prezzi per fornitore
    matrix = {}
    
    # Processiamo prima gli spot storici
    for sku, desc, fornitore_id, prezzo_min in spots:
        if not sku:
            continue
        if sku not in matrix:
            matrix[sku] = {
                "sku_interno": sku,
                "descrizione": desc or f"Prodotto {sku}",
                "prezzi": {}
            }
        matrix[sku]["prezzi"][str(fornitore_id)] = {
            "prezzo": round(float(prezzo_min), 2),
            "tipo": "spot"
        }
        
    # Sovrapponiamo i contratti concordati (hanno priorità rispetto allo spot dello stesso fornitore)
    for sku, desc, fornitore_id, prezzo_pattuito in contracts:
        if not sku:
            continue
        if sku not in matrix:
            matrix[sku] = {
                "sku_interno": sku,
                "descrizione": desc or f"Prodotto {sku}",
                "prezzi": {}
            }
        if desc:
            matrix[sku]["descrizione"] = desc
            
        matrix[sku]["prezzi"][str(fornitore_id)] = {
            "prezzo": round(float(prezzo_pattuito), 2),
            "tipo": "concordato"
        }
        
    # Ordiniamo alfabeticamente per descrizione prodotto
    sorted_matrix = {}
    for sku in sorted(matrix.keys(), key=lambda s: matrix[s]["descrizione"].lower()):
        sorted_matrix[sku] = matrix[sku]
        
    return sorted_matrix


@router.get("/export-vendor-passport/{fornitore_id}", summary="Download Vendor Passport PDF")
async def export_vendor_passport(
    fornitore_id: int,
    data_da: date | None = Query(None, description="Data inizio"),
    data_a: date | None = Query(None, description="Data fine"),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Genera il PDF Business Intelligence per il fornitore.
    """
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None
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
    )
    if data_da:
        stmt = stmt.where(Fattura.data_documento >= data_da)
    if data_a:
        stmt = stmt.where(Fattura.data_documento <= data_a)
    stmt = stmt.distinct()
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


def _extract_informative_keywords(text: str) -> list[str]:
    """Estrae parole chiave significative (solo lettere, lunghezza >= 3) escludendo stop words e unità di misura."""
    import re
    if not text:
        return []
    stop_words = {
        'bev', 'pet', 'per', 'con', 'del', 'dei', 'delle', 'della', 'degli', 'allo', 'alla',
        'alle', 'agli', 'vol', 'cl', 'lt', 'ml', 'gr', 'kg', 'bt', 'pz', 'crt',
        'pac', 'conf', 'cassa', 'bar', 'rist', 'doc', 'dop', 'igp', 'igt', 'san', 'sant',
        'red', 'blue', 'gold', 'plus', 'pro', 'max', 'min', 'net', 'lord', 'art', 'cod',
        'x', 'da', 'di', 'in', 'su', 'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una'
    }
    cleaned = re.sub(r'[^a-zA-Z\s]', ' ', text.lower())
    words = [
        w.strip() for w in cleaned.split() 
        if len(w.strip()) >= 3 and w.strip() not in stop_words and not w.strip().endswith(('cl', 'lt', 'ml', 'gr', 'kg'))
    ]
    return list(dict.fromkeys(words))


async def _resolve_sku_metadata(sku_list: list[str], db: AsyncSession):
    from app.models.products import Product, SupplierProductAlias
    from app.models.alias import AliasProdotto

    sku_synonyms: dict[str, set[str]] = {sku: {sku.lower().strip()} for sku in sku_list}
    sku_keywords: dict[str, list[str]] = {}
    canonical_names: dict[str, str] = {}
    contracts: dict[str, Any] = {}

    for sku in sku_list:
        s_low = sku.lower().strip()
        kws = _extract_informative_keywords(sku)
        sku_keywords[sku] = kws

        # 1. Risoluzione da Product e SupplierProductAlias
        conds = [
            Product.sku_interno == sku,
            func.lower(func.trim(Product.sku_interno)) == s_low,
            Product.canonical_name == sku,
            func.lower(func.trim(Product.canonical_name)) == s_low,
            SupplierProductAlias.raw_description == sku,
            func.lower(func.trim(SupplierProductAlias.raw_description)) == s_low,
            SupplierProductAlias.supplier_code == sku,
            func.lower(func.trim(SupplierProductAlias.supplier_code)) == s_low,
        ]
        if len(kws) >= 2:
            conds.append(and_(*[Product.canonical_name.ilike(f"%{kw}%") for kw in kws]))
            conds.append(and_(*[SupplierProductAlias.raw_description.ilike(f"%{kw}%") for kw in kws]))
        elif len(kws) == 1:
            conds.append(Product.canonical_name.ilike(f"%{kws[0]}%"))
            conds.append(SupplierProductAlias.raw_description.ilike(f"%{kws[0]}%"))

        prod_stmt = (
            select(Product.id, Product.sku_interno, Product.canonical_name)
            .outerjoin(SupplierProductAlias, Product.id == SupplierProductAlias.product_id)
            .where(or_(*conds))
            .distinct()
        )
        prod_res = await db.execute(prod_stmt)
        matched_products = prod_res.all()

        for p_id, p_sku, p_name in matched_products:
            if p_sku:
                sku_synonyms[sku].add(p_sku.lower().strip())
            if p_name:
                sku_synonyms[sku].add(p_name.lower().strip())
                if sku not in canonical_names:
                    canonical_names[sku] = p_name

            if p_id:
                alias_stmt = select(SupplierProductAlias.raw_description, SupplierProductAlias.supplier_code).where(SupplierProductAlias.product_id == p_id)
                alias_res = await db.execute(alias_stmt)
                for a_desc, a_code in alias_res.all():
                    if a_desc:
                        sku_synonyms[sku].add(a_desc.lower().strip())
                    if a_code:
                        sku_synonyms[sku].add(a_code.lower().strip())

        # 2. Risoluzione da AliasProdotto
        alias_p_conds = [
            AliasProdotto.sku_interno == sku,
            func.lower(func.trim(AliasProdotto.sku_interno)) == s_low,
            AliasProdotto.codice_fornitore_originale == sku,
            func.lower(func.trim(AliasProdotto.codice_fornitore_originale)) == s_low,
        ]
        if len(kws) >= 2:
            alias_p_conds.append(and_(*[AliasProdotto.sku_interno.ilike(f"%{kw}%") for kw in kws]))
        alias_p_stmt = select(AliasProdotto.sku_interno, AliasProdotto.codice_fornitore_originale).where(or_(*alias_p_conds))
        alias_p_res = await db.execute(alias_p_stmt)
        for ap_sku, ap_code in alias_p_res.all():
            if ap_sku:
                sku_synonyms[sku].add(ap_sku.lower().strip())
            if ap_code:
                sku_synonyms[sku].add(ap_code.lower().strip())

        # 3. Risoluzione da ListinoMaster
        lm_conds = [
            ListinoMaster.sku_interno == sku,
            func.lower(func.trim(ListinoMaster.sku_interno)) == s_low,
            ListinoMaster.descrizione == sku,
            func.lower(func.trim(ListinoMaster.descrizione)) == s_low,
            ListinoMaster.codice_fornitore == sku,
            func.lower(func.trim(ListinoMaster.codice_fornitore)) == s_low,
        ]
        if len(kws) >= 2:
            lm_conds.append(and_(*[ListinoMaster.descrizione.ilike(f"%{kw}%") for kw in kws]))
        elif len(kws) == 1:
            lm_conds.append(ListinoMaster.descrizione.ilike(f"%{kws[0]}%"))

        lm_stmt = select(ListinoMaster).where(or_(*lm_conds))
        lm_res = await db.execute(lm_stmt)
        for l in lm_res.scalars().all():
            if l.sku_interno:
                sku_synonyms[sku].add(l.sku_interno.lower().strip())
            if l.descrizione:
                sku_synonyms[sku].add(l.descrizione.lower().strip())
            if l.codice_fornitore:
                sku_synonyms[sku].add(l.codice_fornitore.lower().strip())
            if l.data_scadenza is None or sku not in contracts:
                contracts[sku] = l

    return sku_synonyms, sku_keywords, canonical_names, contracts


@router.get("/price-trend/{sku_interno}", summary="Trend Storico Prezzi per SKU")
async def get_price_trend(
    sku_interno: str,
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.esclusi import SKUEscluso

    # Verifica se è escluso
    chk = await db.execute(
        select(SKUEscluso.sku_interno).where(
            or_(
                SKUEscluso.sku_interno == sku_interno,
                func.lower(func.trim(SKUEscluso.sku_interno)) == sku_interno.lower().strip()
            )
        )
    )
    if chk.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Prodotto escluso dalle analisi")

    trends_map = await get_price_trends(skus=sku_interno, _user=_user, db=db)
    if sku_interno in trends_map:
        return trends_map[sku_interno]
    
    # Fallback if mapped under a different key
    for k, v in trends_map.items():
        return v

    return {
        "sku_interno": sku_interno,
        "prodotto_nome": sku_interno,
        "prezzo_contratto_corrente": None,
        "history": []
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
    # Split SKUs
    sku_list = [s.strip() for s in skus.split(",") if s.strip()]
    if not sku_list:
        return {}

    # Filtra SKU esclusi
    from app.models.esclusi import SKUEscluso

    stmt_ex = select(SKUEscluso.sku_interno).where(
        or_(
            SKUEscluso.sku_interno.in_(sku_list),
            func.lower(func.trim(SKUEscluso.sku_interno)).in_([s.lower() for s in sku_list])
        )
    )
    res_ex = await db.execute(stmt_ex)
    excluded = set(s.lower() for s in res_ex.scalars().all())
    sku_list = [s for s in sku_list if s.lower() not in excluded]
    if not sku_list:
        return {}

    sku_synonyms, sku_keywords, canonical_names, contracts = await _resolve_sku_metadata(sku_list, db)

    all_search_terms = list(set().union(*sku_synonyms.values()))
    valid_price = func.coalesce(func.nullif(RigaFattura.prezzo_netto_normalizzato, 0), RigaFattura.prezzo_unitario_fatturato, 0)

    # Costruisci le clausole di matching su righe fattura
    sku_matching_clauses = []
    if all_search_terms:
        sku_matching_clauses.append(func.lower(func.trim(RigaFattura.sku_interno)).in_(all_search_terms))
        sku_matching_clauses.append(func.lower(func.trim(RigaFattura.descrizione_fornitore_raw)).in_(all_search_terms))
        sku_matching_clauses.append(func.lower(func.trim(RigaFattura.codice_fornitore_raw)).in_(all_search_terms))

    for sku, kws in sku_keywords.items():
        if len(kws) >= 2:
            sku_matching_clauses.append(and_(*[RigaFattura.descrizione_fornitore_raw.ilike(f"%{kw}%") for kw in kws]))
            sku_matching_clauses.append(and_(*[RigaFattura.sku_interno.ilike(f"%{kw}%") for kw in kws]))
        elif len(kws) == 1:
            sku_matching_clauses.append(RigaFattura.descrizione_fornitore_raw.ilike(f"%{kws[0]}%"))
            sku_matching_clauses.append(RigaFattura.sku_interno.ilike(f"%{kws[0]}%"))

    # Recupera lo storico degli acquisti cronologicamente con filtri
    stmt = (
        select(
            Fattura.data_documento,
            Fattura.location_id,
            Fattura.fornitore_id,
            RigaFattura.sku_interno,
            RigaFattura.descrizione_fornitore_raw,
            RigaFattura.codice_fornitore_raw,
            valid_price.label("prezzo_pagato"),
            func.coalesce(RigaFattura.quantita, 1).label("quantita"),
            func.coalesce(Fornitore.nome_azienda, "Fornitore non associato").label("fornitore_nome"),
            func.coalesce(Location.nome_struttura, "Tutte le sedi").label("location_nome")
        )
        .join(RigaFattura, RigaFattura.fattura_id == Fattura.id)
        .outerjoin(Fornitore, Fattura.fornitore_id == Fornitore.id)
        .outerjoin(Location, Fattura.location_id == Location.id)
        .where(
            and_(
                valid_price > 0,
                or_(*sku_matching_clauses)
            )
        )
    )

    # Applica i filtri opzionali
    if start_date:
        try:
            s_dt = date.fromisoformat(start_date)
            stmt = stmt.where(Fattura.data_documento >= s_dt)
        except ValueError:
            pass
    if end_date:
        try:
            e_dt = date.fromisoformat(end_date)
            stmt = stmt.where(Fattura.data_documento <= e_dt)
        except ValueError:
            pass
    if location_ids:
        loc_list = [int(lid.strip()) for lid in location_ids.split(",") if lid.strip().isdigit()]
        if loc_list:
            stmt = stmt.where(Fattura.location_id.in_(loc_list))
    if fornitore_ids:
        forn_list = [int(fid.strip()) for fid in fornitore_ids.split(",") if fid.strip().isdigit()]
        if forn_list:
            stmt = stmt.where(Fattura.fornitore_id.in_(forn_list))

    stmt = stmt.order_by(Fattura.data_documento.asc())
    res = await db.execute(stmt)
    history = res.all()

    # Prepara la risposta raggruppata per ciascun SKU richiesto
    response_data = {}
    for sku in sku_list:
        l_active = contracts.get(sku)
        prezzo_contratto = float(l_active.prezzo_pattuito) if l_active and l_active.prezzo_pattuito else None
        prod_name = (l_active.descrizione if l_active and l_active.descrizione else canonical_names.get(sku)) or sku
        response_data[sku] = {
            "sku_interno": sku,
            "prodotto_nome": prod_name,
            "prezzo_contratto_corrente": prezzo_contratto,
            "history": []
        }

    for r in history:
        r_sku = (r.sku_interno or "").strip().lower()
        r_desc = (r.descrizione_fornitore_raw or "").strip().lower()
        r_code = (r.codice_fornitore_raw or "").strip().lower()
        r_combined = f"{r_sku} {r_desc} {r_code}"

        prezzo = float(r.prezzo_pagato) if r.prezzo_pagato is not None else 0.0
        qty = float(r.quantita) if r.quantita is not None else 1.0

        for sku in sku_list:
            syns = sku_synonyms.get(sku, set())
            kws = sku_keywords.get(sku, [])

            matched = (
                r_sku in syns or 
                r_desc in syns or 
                r_code in syns or 
                (len(kws) >= 2 and all(kw in r_combined for kw in kws)) or
                (len(kws) == 1 and kws[0] in r_combined)
            )

            if matched:
                target_key = sku
                if response_data[target_key]["prodotto_nome"] == target_key and r.descrizione_fornitore_raw:
                    response_data[target_key]["prodotto_nome"] = r.descrizione_fornitore_raw

                l_active = contracts.get(target_key)
                prezzo_contratto = float(l_active.prezzo_pattuito) if l_active and l_active.prezzo_pattuito else None

                response_data[target_key]["history"].append({
                    "data": r.data_documento.isoformat() if isinstance(r.data_documento, date) else str(r.data_documento),
                    "prezzo_pagato": prezzo,
                    "quantita": qty,
                    "fornitore": r.fornitore_nome,
                    "location": r.location_nome,
                    "prezzo_contratto": prezzo_contratto
                })

    return response_data


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
            COALESCE(fo.nome_azienda, 'Fornitore ND') as fornitore_ragione_sociale,
            f.fornitore_id,
            to_char(f.data_documento, 'YYYY-MM') as mese,
            AVG(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0)) as prezzo_medio,
            SUM(rf.quantita) as qta_mese_corrente
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        LEFT JOIN fornitori fo ON f.fornitore_id = fo.id
        WHERE rf.sku_interno IS NOT NULL
          AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
          AND (:location_id IS NULL OR f.location_id = :location_id)
          AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
          AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0
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
        (SELECT MIN(COALESCE(NULLIF(rf2.prezzo_netto_normalizzato, 0), rf2.prezzo_unitario_fatturato, 0)) FROM righe_fattura rf2 JOIN fatture f2 ON rf2.fattura_id = f2.id WHERE rf2.sku_interno = lp.prodotto_id AND COALESCE(NULLIF(rf2.prezzo_netto_normalizzato, 0), rf2.prezzo_unitario_fatturato, 0) > 0 AND rf2.is_omaggio IS NOT TRUE) as hist_prezzo_min,
        (SELECT MAX(COALESCE(NULLIF(rf2.prezzo_netto_normalizzato, 0), rf2.prezzo_unitario_fatturato, 0)) FROM righe_fattura rf2 JOIN fatture f2 ON rf2.fattura_id = f2.id WHERE rf2.sku_interno = lp.prodotto_id AND COALESCE(NULLIF(rf2.prezzo_netto_normalizzato, 0), rf2.prezzo_unitario_fatturato, 0) > 0 AND rf2.is_omaggio IS NOT TRUE) as hist_prezzo_max,
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
                AVG(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0)) as prezzo_medio
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            WHERE rf.sku_interno IS NOT NULL
              AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
              AND (:location_id IS NULL OR f.location_id = :location_id)
              AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
              AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0
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
        GROUP BY sku_interno
    )
    SELECT 
        r.sku_interno,
        COALESCE(MAX(lm.descrizione), MAX(r.descrizione_fornitore_raw), r.sku_interno) AS prodotto_nome,
        COALESCE(MAX(f.nome_azienda), MAX(flm.nome_azienda), 'ND') AS fornitore_nome,
        COUNT(r.id) AS numero_acquisti,
        SUM(r.quantita) AS quantita_totale,
        mp.min_price AS prezzo_minimo,
        AVG(COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0)) AS prezzo_medio,
        SUM(GREATEST(0, COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0) - mp.min_price) * r.quantita) AS spreco_totale
    FROM righe_fattura r
    JOIN min_prices mp ON r.sku_interno = mp.sku_interno
    LEFT JOIN fatture ft ON r.fattura_id = ft.id
    LEFT JOIN fornitori f ON ft.fornitore_id = f.id
    LEFT JOIN listino_master lm ON lm.sku_interno = r.sku_interno AND lm.data_scadenza IS NULL
    LEFT JOIN fornitori flm ON flm.id = lm.fornitore_id
    WHERE r.sku_interno IS NOT NULL
      AND r.is_omaggio IS NOT TRUE
    GROUP BY r.sku_interno, mp.min_price
    HAVING SUM(GREATEST(0, COALESCE(NULLIF(r.prezzo_netto_normalizzato, 0), r.prezzo_unitario_fatturato, 0) - mp.min_price) * r.quantita) > 0
    ORDER BY spreco_totale DESC
    LIMIT 10;
    """
    res = await db.execute(text(sql))
    
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
            COALESCE(fo.nome_azienda, 'Fornitore ND') as fornitore_ragione_sociale,
            f.fornitore_id,
            to_char(f.data_documento, 'YYYY-MM') as mese,
            AVG(COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0)) as prezzo_medio,
            SUM(rf.quantita) as qta_mese_corrente
        FROM righe_fattura rf
        JOIN fatture f ON rf.fattura_id = f.id
        LEFT JOIN fornitori fo ON f.fornitore_id = fo.id
        WHERE rf.sku_interno IS NOT NULL
          AND (:location_id IS NULL OR f.location_id = :location_id)
          AND (:anno IS NULL OR to_char(f.data_documento, 'YYYY') = :anno)
          AND COALESCE(NULLIF(rf.prezzo_netto_normalizzato, 0), rf.prezzo_unitario_fatturato, 0) > 0
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
    SELECT 
        rf.sku_interno, 
        MAX(rf.descrizione_fornitore_raw) as descrizione,
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

    pdf_bytes = generate_consumption_invoices_pdf(title, invoices, filter_desc)
    
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
    SELECT 
        rf.sku_interno, 
        MAX(rf.descrizione_fornitore_raw) as descrizione,
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
    for r in res.all():
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

