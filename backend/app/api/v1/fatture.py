"""
Price Sentinel — Fatture Router.
Read-only con filtri per location/fornitore/tipo + marker management.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_from_query
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura, MarkerFattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.anomalie import Anomalia
from app.models.utenti import Utente
from app.schemas.fatture import FatturaResponse, RigaFatturaResponse

router = APIRouter()


@router.get(
    "/",
    summary="Lista fatture con filtri avanzati",
)
async def list_fatture(
    response: Response,
    location_id: int | None = Query(None),
    fornitore_id: int | None = Query(None),
    tipo_documento: str | None = Query(None),
    marker: str | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    search: str | None = Query(None, description="Cerca per numero documento o descrizione prodotto"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Base query with joins for names
    query = (
        select(
            Fattura.id,
            Fattura.numero_documento,
            Fattura.data_documento,
            Fattura.data_ricezione_sdi,
            Fattura.tipo_documento,
            Fattura.totale_imponibile,
            Fattura.marker,
            Fattura.fornitore_id,
            Fattura.location_id,
            Fornitore.nome_azienda.label("fornitore_nome"),
            Location.nome_struttura.label("location_nome"),
            func.count(func.distinct(RigaFattura.id)).label("n_righe"),
            func.count(func.distinct(Anomalia.id)).label("n_anomalie"),
        )
        .outerjoin(Fornitore, Fattura.fornitore_id == Fornitore.id)
        .outerjoin(Location, Fattura.location_id == Location.id)
        .outerjoin(RigaFattura, RigaFattura.fattura_id == Fattura.id)
        .outerjoin(Anomalia, Anomalia.riga_fattura_id == RigaFattura.id)
        .group_by(
            Fattura.id, Fornitore.nome_azienda, Location.nome_struttura
        )
        .order_by(Fattura.data_documento.desc())
    )

    # Manager vede solo la propria location
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)
    elif location_id:
        query = query.where(Fattura.location_id == location_id)

    if fornitore_id:
        query = query.where(Fattura.fornitore_id == fornitore_id)
    if tipo_documento:
        query = query.where(Fattura.tipo_documento == tipo_documento)
    if marker:
        query = query.where(Fattura.marker == marker)
    if data_da:
        query = query.where(Fattura.data_documento >= data_da)
    if data_a:
        query = query.where(Fattura.data_documento <= data_a)
    if search:
        query = query.where(
            Fattura.numero_documento.ilike(f"%{search}%")
        )

    # Count total from the subquery of the filtered base query
    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": r.id,
            "numero_documento": r.numero_documento,
            "data_documento": r.data_documento.isoformat(),
            "data_ricezione_sdi": r.data_ricezione_sdi.isoformat(),
            "tipo_documento": r.tipo_documento.value if hasattr(r.tipo_documento, 'value') else r.tipo_documento,
            "totale_imponibile": float(r.totale_imponibile),
            "marker": r.marker.value if hasattr(r.marker, 'value') else r.marker,
            "fornitore_id": r.fornitore_id,
            "location_id": r.location_id,
            "fornitore_nome": r.fornitore_nome or "Sconosciuto",
            "location_nome": r.location_nome or "N/D",
            "n_righe": r.n_righe,
            "n_anomalie": r.n_anomalie,
        }
        for r in rows
    ]


@router.patch(
    "/{fattura_id}/marker",
    summary="Aggiorna marker fattura",
)
async def update_marker(
    fattura_id: int,
    marker: str = Query(..., description="Nuovo marker"),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Valida marker
    try:
        new_marker = MarkerFattura(marker)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Marker non valido. Valori ammessi: {[m.value for m in MarkerFattura]}"
        )

    result = await db.execute(select(Fattura).where(Fattura.id == fattura_id))
    fattura = result.scalar_one_or_none()
    if not fattura:
        raise HTTPException(status_code=404, detail="Fattura non trovata")

    fattura.marker = new_marker
    await db.flush()
    await db.refresh(fattura)

    return {"id": fattura.id, "marker": fattura.marker.value}


@router.get(
    "/{fattura_id}",
    response_model=FatturaResponse,
    summary="Dettaglio fattura",
)
async def get_fattura(
    fattura_id: int,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Fattura).where(Fattura.id == fattura_id)

    # Manager vede solo la propria location
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)

    result = await db.execute(query)
    fattura = result.scalar_one_or_none()
    if not fattura:
        raise HTTPException(status_code=404, detail="Fattura non trovata")
    return fattura


@router.get(
    "/{fattura_id}/righe",
    response_model=list[RigaFatturaResponse],
    summary="Righe fattura",
)
async def list_righe_fattura(
    fattura_id: int,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verifica accesso alla fattura
    fattura_query = select(Fattura).where(Fattura.id == fattura_id)
    if current_user.ruolo.value == "manager" and current_user.location_id:
        fattura_query = fattura_query.where(
            Fattura.location_id == current_user.location_id
        )
    fattura_result = await db.execute(fattura_query)
    fattura = fattura_result.scalar_one_or_none()
    if not fattura:
        raise HTTPException(status_code=404, detail="Fattura non trovata")

    result = await db.execute(
        select(RigaFattura)
        .where(RigaFattura.fattura_id == fattura_id)
        .order_by(RigaFattura.numero_linea)
    )
    righe = result.scalars().all()

    # Resolve commercial agreement (PFA) details for each matched line item
    skus = [r.sku_interno for r in righe if r.sku_interno]
    if skus:
        from app.models.listino import ListinoMaster, PFATipo
        from decimal import Decimal
        listino_query = select(ListinoMaster).where(
            and_(
                ListinoMaster.fornitore_id == fattura.fornitore_id,
                ListinoMaster.sku_interno.in_(skus),
                ListinoMaster.data_inizio_validita <= fattura.data_documento,
                (ListinoMaster.data_scadenza.is_(None) | (ListinoMaster.data_scadenza >= fattura.data_documento))
            )
        ).options(selectinload(ListinoMaster.pfa_scaglioni))
        listino_res = await db.execute(listino_query)
        listini = listino_res.scalars().all()
        sku_to_listino = {lst.sku_interno: lst for lst in listini}

        # Pre-query cumulative year-to-date spent per SKU for scaglioni if there are scaglioni agreements
        has_scaglioni = any(l.pfa_tipo == PFATipo.scaglioni for l in listini)
        sku_to_cumulative_spent = {}
        if has_scaglioni:
            year_start = date(fattura.data_documento.year, 1, 1)
            spent_query = select(
                RigaFattura.sku_interno,
                func.sum(
                    func.coalesce(
                        # Subtract if credit note, else add
                        func.distinct(
                            func.case(
                                (Fattura.tipo_documento == "TD04", -RigaFattura.prezzo_netto_normalizzato * RigaFattura.quantita),
                                else_=RigaFattura.prezzo_netto_normalizzato * RigaFattura.quantita
                            )
                        ),
                        Decimal("0.0")
                    )
                )
            ).join(Fattura).where(
                and_(
                    Fattura.fornitore_id == fattura.fornitore_id,
                    RigaFattura.sku_interno.in_(skus),
                    Fattura.data_documento >= year_start,
                    Fattura.data_documento <= fattura.data_documento
                )
            ).group_by(RigaFattura.sku_interno)
            spent_res = await db.execute(spent_query)
            for row in spent_res.all():
                sku_to_cumulative_spent[row[0]] = Decimal(str(row[1] or "0.0"))

        for riga in righe:
            if riga.sku_interno in sku_to_listino:
                lst = sku_to_listino[riga.sku_interno]
                riga.pfa_tipo = lst.pfa_tipo.value if (lst.pfa_tipo and hasattr(lst.pfa_tipo, 'value')) else lst.pfa_tipo
                riga.pfa_valore = lst.pfa_valore
                
                # Calculate the netto_rientro unit price
                prezzo_netto = Decimal(str(riga.prezzo_netto_normalizzato))
                if lst.pfa_tipo == PFATipo.fisso and lst.pfa_valore:
                    riga.netto_rientro = prezzo_netto - Decimal(str(lst.pfa_valore))
                elif lst.pfa_tipo == PFATipo.percentuale and lst.pfa_valore:
                    riga.netto_rientro = prezzo_netto * (Decimal("1.0") - Decimal(str(lst.pfa_valore)))
                elif lst.pfa_tipo == PFATipo.scaglioni and lst.pfa_scaglioni:
                    cumulative = sku_to_cumulative_spent.get(riga.sku_interno, Decimal("0.0"))
                    active_pct = Decimal("0.0")
                    for sc in lst.pfa_scaglioni:
                        soglia_da = Decimal(str(sc.soglia_da))
                        soglia_a = Decimal(str(sc.soglia_a)) if sc.soglia_a is not None else None
                        if cumulative >= soglia_da:
                            if soglia_a is None or cumulative < soglia_a:
                                active_pct = Decimal(str(sc.valore_percentuale))
                                break
                    if active_pct == Decimal("0.0") and lst.pfa_scaglioni:
                        matching_scs = [sc for sc in lst.pfa_scaglioni if cumulative >= Decimal(str(sc.soglia_da))]
                        if matching_scs:
                            matching_scs.sort(key=lambda x: x.soglia_da, reverse=True)
                            active_pct = Decimal(str(matching_scs[0].valore_percentuale))
                    
                    riga.netto_rientro = prezzo_netto * (Decimal("1.0") - active_pct)

    return righe


@router.get(
    "/{fattura_id}/html",
    response_class=HTMLResponse,
    summary="Anteprima originale leggibile della fattura (HTML)",
)
async def get_fattura_html(
    fattura_id: int,
    current_user: Utente = Depends(get_current_user_from_query),
    db: AsyncSession = Depends(get_db),
):
    import html
    from sqlalchemy.orm import selectinload

    # Recupera la fattura con join su Fornitore e Location
    query = (
        select(Fattura)
        .options(selectinload(Fattura.fornitore), selectinload(Fattura.location))
        .where(Fattura.id == fattura_id)
    )
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)

    result = await db.execute(query)
    fattura = result.scalar_one_or_none()
    if not fattura:
        raise HTTPException(
            status_code=404, 
            detail="Fattura non trovata o accesso non autorizzato"
        )

    # Carica le righe di dettaglio
    righe_res = await db.execute(
        select(RigaFattura)
        .where(RigaFattura.fattura_id == fattura_id)
        .order_by(RigaFattura.numero_linea)
    )
    righe = righe_res.scalars().all()

    # Prepara dati per il rendering, applicando html.escape per sicurezza (XSS prevention)
    num_doc = html.escape(fattura.numero_documento)
    data_doc = fattura.data_documento.strftime("%d/%m/%Y")
    data_sdi = fattura.data_ricezione_sdi.strftime("%d/%m/%Y")
    tipo_doc = html.escape(fattura.tipo_documento.value if hasattr(fattura.tipo_documento, "value") else str(fattura.tipo_documento))
    totale_imp = f"{fattura.totale_imponibile:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    marker_val = fattura.marker.value if hasattr(fattura.marker, "value") else str(fattura.marker)
    marker_esc = html.escape(marker_val)

    # Fornitore
    forn_nome = html.escape(fattura.fornitore.nome_azienda)
    forn_piva = html.escape(fattura.fornitore.partita_iva)
    forn_email = html.escape(fattura.fornitore.email_contatto or "N/D")

    # Location
    loc_nome = html.escape(fattura.location.nome_struttura)
    loc_piva = html.escape(fattura.location.piva_riferimento)
    loc_tipo = html.escape(fattura.location.tipologia.value if hasattr(fattura.location.tipologia, "value") else str(fattura.location.tipologia))

    # Badge class per il marker
    marker_badge_style = {
        "nessuno": "border: 1px solid rgba(255,255,255,0.15); color: #94a3b8; background: rgba(148,163,184,0.05);",
        "da_verificare": "border: 1px solid rgba(245,158,11,0.3); color: #fbbf24; background: rgba(245,158,11,0.05);",
        "verificata": "border: 1px solid rgba(16,185,129,0.3); color: #34d399; background: rgba(16,185,129,0.05);",
        "contestata": "border: 1px solid rgba(239,68,68,0.3); color: #f87171; background: rgba(239,68,68,0.05);",
        "approvata": "border: 1px solid rgba(59,130,246,0.3); color: #60a5fa; background: rgba(59,130,246,0.05);",
        "sospesa": "border: 1px solid rgba(139,92,246,0.3); color: #a78bfa; background: rgba(139,92,246,0.05);",
    }.get(marker_val, "border: 1px solid rgba(255,255,255,0.1); color: white;")

    # Righe di dettaglio HTML
    righe_html = ""
    for r in righe:
        r_num = r.numero_linea
        r_cod = html.escape(r.codice_fornitore_raw or "-")
        r_desc = html.escape(r.descrizione_fornitore_raw or "Prodotto senza descrizione")
        r_sku = html.escape(r.sku_interno or "-")
        r_qty = f"{r.quantita:g}"
        r_pu = f"€ {r.prezzo_unitario_fatturato:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        r_sconto = f"{r.sconto_percentuale:g}%" if r.sconto_percentuale > 0 else "-"
        r_net = f"€ {r.prezzo_netto_normalizzato:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        tot_net_val = r.prezzo_netto_normalizzato * r.quantita
        r_tot_net = f"€ {tot_net_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        r_iva = f"{r.aliquota_iva:g}%" if r.aliquota_iva is not None else "-"
        
        # Stato matching
        stato_m = r.stato_matching.value if hasattr(r.stato_matching, "value") else str(r.stato_matching)
        stato_badge = {
            "matched": '<span style="color: #34d399; background: rgba(16,185,129,0.1); padding: 2px 8px; border-radius: 4px; font-weight: 500; font-size: 0.75rem;">Matched</span>',
            "in_parking": '<span style="color: #fbbf24; background: rgba(245,158,11,0.1); padding: 2px 8px; border-radius: 4px; font-weight: 500; font-size: 0.75rem;">In Parking</span>',
            "no_match": '<span style="color: #94a3b8; background: rgba(148,163,184,0.1); padding: 2px 8px; border-radius: 4px; font-weight: 500; font-size: 0.75rem;">No Match</span>',
        }.get(stato_m, f"<span>{html.escape(stato_m)}</span>")

        righe_html += f"""
        <tr>
            <td style="text-align: center;">{r_num}</td>
            <td>{r_cod}</td>
            <td style="font-weight: 500;">{r_desc}</td>
            <td style="color: #818cf8; font-family: monospace;">{r_sku}</td>
            <td style="text-align: right;">{r_qty}</td>
            <td style="text-align: right;">{r_pu}</td>
            <td style="text-align: right; color: #fbbf24;">{r_sconto}</td>
            <td style="text-align: right; font-weight: 600; color: #34d399;">{r_net}</td>
            <td style="text-align: right; font-weight: 600;">{r_tot_net}</td>
            <td style="text-align: center;">{r_iva}</td>
            <td style="text-align: center;">{stato_badge}</td>
        </tr>
        """

    # Template HTML completo
    content = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fattura N. {num_doc} - Price Sentinel</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #09090e;
            --bg-secondary: #13131c;
            --border-glass: rgba(255, 255, 255, 0.05);
            --text-primary: #ffffff;
            --text-secondary: #94a3b8;
            --accent-blue: #3b82f6;
            --accent-indigo: #6366f1;
        }}
        
        * {{
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Outfit', sans-serif;
            background: radial-gradient(circle at top, #111118 0%, var(--bg-primary) 100%);
            color: var(--text-primary);
            margin: 0;
            padding: 40px 20px;
            min-height: 100vh;
            line-height: 1.5;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 30px;
        }}

        .no-print-toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-glass);
            border-radius: 12px;
            padding: 16px 24px;
            backdrop-filter: blur(10px);
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 700;
            font-size: 1.2rem;
            letter-spacing: -0.02em;
        }}
        .brand span {{
            color: var(--accent-indigo);
        }}

        .btn-print {{
            background: linear-gradient(135deg, var(--accent-blue) 0%, var(--accent-indigo) 100%);
            color: white;
            border: none;
            padding: 10px 20px;
            font-size: 0.9rem;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: opacity 0.2s;
        }}
        .btn-print:hover {{
            opacity: 0.9;
        }}

        .glass-panel {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }}

        .invoice-header-grid {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
            align-items: start;
        }}

        .invoice-title-area {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}

        .invoice-badge {{
            display: inline-flex;
            align-self: flex-start;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            margin-top: 24px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 20px;
        }}

        .meta-item {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}

        .meta-label {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .meta-value {{
            font-size: 1.1rem;
            font-weight: 600;
        }}

        .parties-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}

        .party-card {{
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}

        .party-title {{
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--accent-indigo);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid rgba(99, 102, 241, 0.2);
            padding-bottom: 8px;
            margin: 0;
        }}

        .party-detail {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}

        .party-name {{
            font-size: 1.2rem;
            font-weight: 600;
        }}

        .party-info {{
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}

        .table-container {{
            overflow-x: auto;
            margin-top: 8px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }}

        th {{
            border-bottom: 2px solid rgba(255, 255, 255, 0.08);
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
            padding: 12px 8px;
            text-align: left;
        }}

        td {{
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            padding: 14px 8px;
            color: var(--text-primary);
        }}

        tr:hover td {{
            background: rgba(255, 255, 255, 0.01);
        }}

        .totals-section {{
            display: flex;
            justify-content: flex-end;
            margin-top: 10px;
        }}

        .totals-box {{
            width: 320px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding-top: 16px;
        }}

        .total-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .total-label {{
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}

        .total-value {{
            font-size: 1rem;
            font-weight: 600;
        }}

        .grand-total {{
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            padding-top: 12px;
            margin-top: 4px;
        }}
        .grand-total .total-label {{
            font-size: 1rem;
            font-weight: 700;
            color: white;
        }}
        .grand-total .total-value {{
            font-size: 1.4rem;
            font-weight: 700;
            color: #34d399;
        }}

        /* Print styles */
        @media print {{
            body {{
                background: white !important;
                color: #000000 !important;
                padding: 0 !important;
                font-size: 9pt !important;
            }}
            .no-print {{
                display: none !important;
            }}
            .glass-panel {{
                background: none !important;
                border: none !important;
                border-bottom: 1px solid #ddd !important;
                box-shadow: none !important;
                padding: 10px 0 !important;
                border-radius: 0 !important;
                color: #000 !important;
            }}
            .glass-panel:last-child {{
                border-bottom: none !important;
            }}
            .party-title {{
                color: #000 !important;
                border-bottom: 1px solid #000 !important;
            }}
            th {{
                color: #000 !important;
                border-bottom: 2px solid #000 !important;
            }}
            td {{
                color: #000 !important;
                border-bottom: 1px solid #ddd !important;
            }}
            .grand-total .total-label, .grand-total .total-value {{
                color: #000 !important;
            }}
            .invoice-badge {{
                border: 1px solid #000 !important;
                color: #000 !important;
                background: none !important;
            }}
            .parties-grid {{
                grid-template-columns: 1fr 1fr !important;
                gap: 40px !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- TOP TOOLBAR (HIDDEN IN PRINT) -->
        <div class="no-print-toolbar no-print">
            <div class="brand">
                PRICE <span>SENTINEL</span>
            </div>
            <button class="btn-print" onclick="window.print()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-top:-1px"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>
                Stampa Documento
            </button>
        </div>

        <!-- HEADER SUMMARY PANEL -->
        <div class="glass-panel">
            <div class="invoice-header-grid">
                <div class="invoice-title-area">
                    <span style="font-size: 0.85rem; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.05em; font-weight: 500;">Fattura Elettronica</span>
                    <h2 style="margin: 4px 0 10px 0; font-size: 1.8rem; font-weight: 700; letter-spacing: -0.02em;">N. {num_doc}</h2>
                    <div class="invoice-badge" style="{marker_badge_style}">
                        Marker: {marker_esc}
                    </div>
                </div>
            </div>

            <div class="meta-grid">
                <div class="meta-item">
                    <span class="meta-label">Data Documento</span>
                    <span class="meta-value">{data_doc}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Ricezione SDI</span>
                    <span class="meta-value">{data_sdi}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Tipo Documento</span>
                    <span class="meta-value">{tipo_doc}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Totale Imponibile</span>
                    <span class="meta-value" style="color: #34d399;">€ {totale_imp}</span>
                </div>
            </div>
        </div>

        <!-- PARTIES PANEL -->
        <div class="glass-panel">
            <div class="parties-grid">
                <!-- CEDENTE (SUPPLIER) -->
                <div class="party-card">
                    <h3 class="party-title">Cedente (Fornitore)</h3>
                    <div class="party-detail">
                        <div class="party-name">{forn_nome}</div>
                        <div class="party-info"><strong>Partita IVA:</strong> {forn_piva}</div>
                        <div class="party-info"><strong>Email:</strong> {forn_email}</div>
                    </div>
                </div>

                <!-- CESSIONARIO (CLIENT / LOCATION) -->
                <div class="party-card">
                    <h3 class="party-title">Cessionario (Cliente)</h3>
                    <div class="party-detail">
                        <div class="party-name">{loc_nome}</div>
                        <div class="party-info"><strong>Partita IVA:</strong> {loc_piva}</div>
                        <div class="party-info"><strong>Tipologia Struttura:</strong> {loc_tipo}</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- RIGHE DI DETTAGLIO -->
        <div class="glass-panel">
            <h3 style="margin-top: 0; margin-bottom: 20px; font-size: 1.05rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent-indigo)">Dettaglio Righe Documento</h3>
            
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th style="width: 40px; text-align: center;">Lin.</th>
                            <th style="width: 120px;">Cod. Fornitore</th>
                            <th>Descrizione Prodotto</th>
                            <th style="width: 140px;">SKU Interno</th>
                            <th style="width: 70px; text-align: right;">Q.tà</th>
                            <th style="width: 90px; text-align: right;">Prezzo Unit.</th>
                            <th style="width: 70px; text-align: right;">Sconto</th>
                            <th style="width: 100px; text-align: right;">Prezzo Netto</th>
                            <th style="width: 110px; text-align: right;">Importo Netto</th>
                            <th style="width: 60px; text-align: center;">Aliq.</th>
                            <th style="width: 100px; text-align: center;">Matching</th>
                        </tr>
                    </thead>
                    <tbody>
                        {righe_html}
                    </tbody>
                </table>
            </div>

            <!-- TOTALS ROW -->
            <div class="totals-section">
                <div class="totals-box">
                    <div class="total-row">
                        <span class="total-label">Numero Linee</span>
                        <span class="total-value">{len(righe)}</span>
                    </div>
                    <div class="total-row grand-total">
                        <span class="total-label">Totale Imponibile</span>
                        <span class="total-value">€ {totale_imp}</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=content, status_code=200)
