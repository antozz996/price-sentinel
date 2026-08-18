"""
Price Sentinel — Listino Master Router.
CRUD Append-Only con versioning — Spec §4.4.
Include gestione PFA Scaglioni, UoM Conversioni, Import/Export Excel.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.listino import ListinoMaster, PFAScaglione, PFATipo, UoMConversione
from app.models.utenti import Utente
from app.schemas.listino import (
    ListinoCreate,
    ListinoResponse,
    ListinoUpdate,
    PFAScaglioneCreate,
    PFAScaglioneResponse,
    UoMConversioneCreate,
    UoMConversioneResponse,
)
from app.services.excel_import import (
    generate_template_excel,
    generate_extracted_listino_excel,
    parse_listino_excel,
)

router = APIRouter()


# ─────────────────────────────────────────────
# Listino Master
# ─────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[ListinoResponse],
    summary="Lista listino (record attivi)",
)
async def list_listino(
    response: Response,
    fornitore_id: int | None = Query(None),
    include_scaduti: bool = Query(False, description="Includi record scaduti"),
    limit: int = Query(50, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ListinoMaster).order_by(ListinoMaster.sku_interno)

    if fornitore_id:
        query = query.where(ListinoMaster.fornitore_id == fornitore_id)

    if not include_scaduti:
        query = query.where(ListinoMaster.data_scadenza.is_(None))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    # Slice results
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/",
    response_model=ListinoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea voce listino",
)
async def create_listino(
    data: ListinoCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    listino = ListinoMaster(
        fornitore_id=data.fornitore_id,
        sku_interno=data.sku_interno,
        descrizione=data.descrizione,
        prezzo_pattuito=data.prezzo_pattuito,
        unita_misura=data.unita_misura,
        data_inizio_validita=data.data_inizio_validita,
        data_scadenza=data.data_scadenza,
        pfa_tipo=PFATipo(data.pfa_tipo) if data.pfa_tipo else None,
        pfa_valore=data.pfa_valore,
    )
    db.add(listino)
    await db.flush()
    await db.refresh(listino)
    return listino


# ─────────────────────────────────────────────
# Import / Export Excel — Sprint 1
# ─────────────────────────────────────────────

@router.get(
    "/template-excel",
    summary="Download Template Excel Listino",
    description="Scarica il template .xlsx standard per l'import massivo del listino.",
)
async def download_template_excel(
    fornitore_nome: str = Query("NomeFornitore", description="Nome del fornitore per il titolo"),
    _admin: Utente = Depends(require_admin),
):
    content = generate_template_excel(fornitore_nome)
    filename = f"template_listino_{fornitore_nome.replace(' ', '_').lower()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/import-excel/{fornitore_id}",
    summary="Import Listino da Excel",
    description=(
        "Carica un file .xlsx per importare massivamente le voci del listino. "
        "Usa dry_run=true per validare senza inserire. "
        "Restituisce un report dettagliato con errori per riga."
    ),
)
async def import_listino_excel(
    fornitore_id: int,
    file: UploadFile = File(..., description="File Excel .xlsx con il listino"),
    dry_run: bool = Query(False, description="Se true, valida senza inserire"),
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Validazione tipo file
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Formato non supportato. Usa un file .xlsx (Excel)",
        )

    # Verifica fornitore esiste
    from app.models.fornitori import Fornitore
    forn_result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = forn_result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    # Parse e valida
    import io
    file_data = io.BytesIO(await file.read())
    parse_result = parse_listino_excel(file_data, fornitore_id)

    if dry_run or not parse_result.is_valid:
        return {
            "mode": "dry_run" if dry_run else "validation_failed",
            "fornitore": fornitore.nome_azienda,
            **parse_result.to_dict(),
        }

    inserted = 0
    skipped = 0
    updated = 0
    from datetime import date

    for record in parse_result.records:
        # Check duplicato SKU attivo per lo stesso fornitore
        existing = await db.execute(
            select(ListinoMaster).where(
                and_(
                    ListinoMaster.fornitore_id == fornitore_id,
                    ListinoMaster.sku_interno == record["sku_interno"],
                    ListinoMaster.data_scadenza.is_(None),
                )
            )
        )
        existing_listino = existing.scalar_one_or_none()
        
        new_pfa_tipo = PFATipo(record["pfa_tipo"].lower()) if record.get("pfa_tipo") else None
        
        if existing_listino:
            # Check se i valori sono identici (nessun aggiornamento necessario)
            old_pfa_tipo = existing_listino.pfa_tipo
            old_pfa_valore = existing_listino.pfa_valore
            
            if (float(existing_listino.prezzo_pattuito) == float(record["prezzo_pattuito"]) and
                existing_listino.unita_misura == record["unita_misura"] and
                old_pfa_tipo == new_pfa_tipo and
                old_pfa_valore == record.get("pfa_valore")):
                skipped += 1
                continue
            
            # Valori cambiati: storicizza il vecchio
            existing_listino.data_scadenza = date.today()
            updated += 1
        else:
            inserted += 1

        listino = ListinoMaster(
            fornitore_id=record["fornitore_id"],
            sku_interno=record["sku_interno"],
            descrizione=record["descrizione"],
            prezzo_pattuito=record["prezzo_pattuito"],
            unita_misura=record["unita_misura"],
            data_inizio_validita=record["data_inizio_validita"],
            data_scadenza=None,
            pfa_tipo=new_pfa_tipo,
            pfa_valore=record.get("pfa_valore"),
        )
        db.add(listino)

    await db.flush()

    return {
        "mode": "imported",
        "fornitore": fornitore.nome_azienda,
        "total_rows": parse_result.total_rows,
        "inserted": inserted,
        "updated": updated,
        "skipped_duplicates": skipped,
        "errors_count": 0,
    }


@router.post(
    "/import-multi-supplier",
    summary="Importa Listino Comparativo Multi-Fornitore",
    description=(
        "Carica un file Excel con colonne per molteplici fornitori. "
        "Identifica automaticamente i fornitori, li crea se mancanti, "
        "e carica i relativi prezzi a listino con logica append-only."
    ),
)
async def import_multi_supplier(
    file: UploadFile = File(..., description="File Excel .xlsx comparativo"),
    dry_run: bool = Query(False, description="Se true, valida senza inserire"),
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Validazione tipo file
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Formato non supportato. Usa un file .xlsx (Excel)",
        )

    import io
    from app.services.excel_import_multi import parse_multi_supplier_excel, generate_deterministic_piva
    from app.models.fornitori import Fornitore
    from app.models.listino import ListinoMaster
    from sqlalchemy import select, func, and_
    from datetime import date

    file_data = io.BytesIO(await file.read())
    parse_result = parse_multi_supplier_excel(file_data)

    if dry_run or not parse_result.is_valid:
        return {
            "mode": "dry_run" if dry_run else "validation_failed",
            **parse_result.to_dict(),
        }

    # Mappa i nomi dei fornitori rilevati ad ID del database (o creali)
    suppliers_map = {}
    for name in parse_result.suppliers_detected:
        # Search by name (case-insensitive)
        stmt = select(Fornitore).where(func.lower(Fornitore.nome_azienda) == name.lower())
        res = await db.execute(stmt)
        forn = res.scalar_one_or_none()
        
        if not forn:
            # Genera P.IVA deterministica
            piva = generate_deterministic_piva(name)
            # Verifica se esiste già un fornitore con questa P.IVA (es. creato in precedenza)
            piva_stmt = select(Fornitore).where(Fornitore.partita_iva == piva)
            piva_res = await db.execute(piva_stmt)
            forn = piva_res.scalar_one_or_none()
            
            if not forn:
                # Crea nuovo fornitore
                forn = Fornitore(
                    nome_azienda=name.upper(),
                    partita_iva=piva,
                    attivo_whitelist=True
                )
                db.add(forn)
                await db.flush()
        
        suppliers_map[name] = forn

    inserted = 0
    updated = 0
    skipped = 0
    today = date.today()

    for record in parse_result.records:
        sku = record["sku_interno"]
        desc = record["descrizione"]
        uom = record["unita_misura"]
        
        for name, price in record["prezzi"].items():
            fornitore = suppliers_map[name]
            fornitore_id = fornitore.id
            
            # Cerca duplicato SKU attivo per lo stesso fornitore
            existing = await db.execute(
                select(ListinoMaster).where(
                    and_(
                        ListinoMaster.fornitore_id == fornitore_id,
                        ListinoMaster.sku_interno == sku,
                        ListinoMaster.data_scadenza.is_(None),
                    )
                )
            )
            existing_listino = existing.scalar_one_or_none()
            
            if existing_listino:
                # Se il prezzo è identico, salta
                if float(existing_listino.prezzo_pattuito) == float(price) and existing_listino.unita_misura == uom:
                    skipped += 1
                    continue
                
                # Prezzo cambiato: storicizza il vecchio
                existing_listino.data_scadenza = today
                updated += 1
            else:
                inserted += 1

            # Inserisci il nuovo record listino
            listino = ListinoMaster(
                fornitore_id=fornitore_id,
                sku_interno=sku,
                descrizione=desc,
                prezzo_pattuito=price,
                unita_misura=uom,
                data_inizio_validita=today,
                data_scadenza=None,
                pfa_tipo=None,
                pfa_valore=None,
            )
            db.add(listino)

    await db.flush()

    return {
        "mode": "imported",
        "total_rows": parse_result.total_rows,
        "suppliers_detected": parse_result.suppliers_detected,
        "inserted": inserted,
        "updated": updated,
        "skipped_duplicates": skipped,
        "errors_count": 0,
    }


# ─────────────────────────────────────────────
# Estrazione Listino da Storico Fatture
# ─────────────────────────────────────────────

@router.get(
    "/extract-from-invoices/{fornitore_id}",
    summary="Estrai Listino da Storico Fatture",
    description="Aggrega gli articoli fatturati dal fornitore ed estrae i prezzi (ultimo, minimo, medio).",
)
async def extract_listino_from_invoices(
    fornitore_id: int,
    price_strategy: str = Query("latest", regex="^(latest|min|avg)$", description="latest, min o avg"),
    format: str = Query("json", regex="^(json|excel)$", description="json o excel"),
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.fornitori import Fornitore
    from app.models.fatture import Fattura, RigaFattura, TipoDocumento
    from decimal import Decimal

    fornitore = await db.get(Fornitore, fornitore_id)
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    stmt = (
        select(
            RigaFattura.codice_fornitore_raw,
            RigaFattura.descrizione_fornitore_raw,
            RigaFattura.unita_misura_fattura,
            RigaFattura.prezzo_netto_normalizzato,
            RigaFattura.quantita,
            RigaFattura.sku_interno,
            Fattura.data_documento,
            Fattura.numero_documento,
        )
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .where(
            Fattura.fornitore_id == fornitore_id,
            Fattura.tipo_documento == TipoDocumento.TD01,
            RigaFattura.is_omaggio.is_(False),
            RigaFattura.descrizione_fornitore_raw.is_not(None),
        )
        .order_by(Fattura.data_documento.desc(), RigaFattura.id.desc())
    )
    rows = (await db.execute(stmt)).all()

    grouped = {}
    for code, desc, uom, price, qty, sku, doc_date, doc_num in rows:
        clean_desc = (desc or "").strip()
        if not clean_desc:
            continue
        clean_code = (code or "").strip()
        key = (clean_code.upper(), clean_desc.upper(), (uom or "Pz").upper())

        if key not in grouped:
            supp_prefix = "".join(c for c in fornitore.nome_azienda[:3] if c.isalnum()).upper() or "SKU"
            clean_sku = sku or (f"{supp_prefix}-{clean_code}" if clean_code else f"{supp_prefix}-{clean_desc[:12].replace(' ', '-').upper()}")
            grouped[key] = {
                "sku_interno": clean_sku,
                "descrizione": clean_desc,
                "codice_fornitore": clean_code or None,
                "unita_misura": uom or "Pz",
                "prices": [],
                "quantities": [],
                "dates": [],
                "latest_price": price or Decimal("0"),
                "latest_date": doc_date,
                "latest_doc": doc_num,
            }

        grouped[key]["prices"].append(Decimal(str(price or 0)))
        grouped[key]["quantities"].append(Decimal(str(qty or 1)))
        if doc_date:
            grouped[key]["dates"].append(doc_date)

    items = []
    for g in grouped.values():
        prices = g["prices"]
        qtys = g["quantities"]

        if price_strategy == "min":
            chosen_price = min(prices) if prices else Decimal("0")
        elif price_strategy == "avg":
            total_spend = sum(p * q for p, q in zip(prices, qtys))
            total_qty = sum(qtys)
            chosen_price = (total_spend / total_qty).quantize(Decimal("0.0001")) if total_qty > 0 else (sum(prices) / len(prices)).quantize(Decimal("0.0001"))
        else:
            chosen_price = g["latest_price"]

        items.append({
            "sku_interno": g["sku_interno"],
            "descrizione": g["descrizione"],
            "codice_fornitore": g["codice_fornitore"],
            "prezzo_pattuito": float(chosen_price),
            "unita_misura": g["unita_misura"],
            "data_inizio_validita": g["latest_date"].strftime("%d/%m/%Y") if g["latest_date"] else date.today().strftime("%d/%m/%Y"),
            "ultima_data": g["latest_date"].strftime("%d/%m/%Y") if g["latest_date"] else "",
            "totale_acquistato": float(sum(qtys)),
            "occorrenze": len(prices),
        })

    items.sort(key=lambda x: x["descrizione"])

    if format == "excel":
        excel_bytes = generate_extracted_listino_excel(fornitore.nome_azienda, items)
        safe_name = "".join(c for c in fornitore.nome_azienda if c.isalnum() or c in " _-").strip().replace(" ", "_")
        filename = f"listino_estratto_{safe_name}_{date.today().strftime('%Y%m%d')}.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "fornitore_id": fornitore.id,
        "fornitore_nome": fornitore.nome_azienda,
        "total_items": len(items),
        "price_strategy": price_strategy,
        "items": items,
    }


@router.post(
    "/import-from-invoices/{fornitore_id}",
    summary="Importa direttamente a Listino Master da Fatture",
    description="Crea o aggiorna le voci di Listino Master a partire dallo storico fatture.",
)
async def import_from_invoices_direct(
    fornitore_id: int,
    price_strategy: str = Query("latest", regex="^(latest|min|avg)$"),
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.fornitori import Fornitore
    from app.models.fatture import Fattura, RigaFattura, TipoDocumento
    from decimal import Decimal

    fornitore = await db.get(Fornitore, fornitore_id)
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    # Fetch and aggregate
    stmt = (
        select(
            RigaFattura.codice_fornitore_raw,
            RigaFattura.descrizione_fornitore_raw,
            RigaFattura.unita_misura_fattura,
            RigaFattura.prezzo_netto_normalizzato,
            RigaFattura.quantita,
            RigaFattura.sku_interno,
            Fattura.data_documento,
        )
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .where(
            Fattura.fornitore_id == fornitore_id,
            Fattura.tipo_documento == TipoDocumento.TD01,
            RigaFattura.is_omaggio.is_(False),
            RigaFattura.descrizione_fornitore_raw.is_not(None),
        )
        .order_by(Fattura.data_documento.desc(), RigaFattura.id.desc())
    )
    rows = (await db.execute(stmt)).all()

    grouped = {}
    for code, desc, uom, price, qty, sku, doc_date in rows:
        clean_desc = (desc or "").strip()
        if not clean_desc:
            continue
        clean_code = (code or "").strip()
        key = (clean_code.upper(), clean_desc.upper(), (uom or "Pz").upper())

        if key not in grouped:
            supp_prefix = "".join(c for c in fornitore.nome_azienda[:3] if c.isalnum()).upper() or "SKU"
            clean_sku = sku or (f"{supp_prefix}-{clean_code}" if clean_code else f"{supp_prefix}-{clean_desc[:12].replace(' ', '-').upper()}")
            grouped[key] = {
                "sku_interno": clean_sku,
                "descrizione": clean_desc,
                "unita_misura": uom or "Pz",
                "prices": [],
                "quantities": [],
                "latest_price": price or Decimal("0"),
                "latest_date": doc_date,
            }

        grouped[key]["prices"].append(Decimal(str(price or 0)))
        grouped[key]["quantities"].append(Decimal(str(qty or 1)))

    inserted = 0
    updated = 0
    skipped = 0
    today = date.today()

    for g in grouped.values():
        prices = g["prices"]
        qtys = g["quantities"]

        if price_strategy == "min":
            chosen_price = min(prices) if prices else Decimal("0")
        elif price_strategy == "avg":
            total_spend = sum(p * q for p, q in zip(prices, qtys))
            total_qty = sum(qtys)
            chosen_price = (total_spend / total_qty).quantize(Decimal("0.0001")) if total_qty > 0 else (sum(prices) / len(prices)).quantize(Decimal("0.0001"))
        else:
            chosen_price = g["latest_price"]

        sku = g["sku_interno"]
        desc = g["descrizione"]
        uom = g["unita_misura"]

        # Check if already in listino
        existing = await db.execute(
            select(ListinoMaster).where(
                and_(
                    ListinoMaster.fornitore_id == fornitore_id,
                    ListinoMaster.sku_interno == sku,
                    ListinoMaster.data_scadenza.is_(None),
                )
            )
        )
        existing_listino = existing.scalar_one_or_none()

        if existing_listino:
            if float(existing_listino.prezzo_pattuito) == float(chosen_price):
                skipped += 1
                continue
            existing_listino.data_scadenza = today
            updated += 1
        else:
            inserted += 1

        listino = ListinoMaster(
            fornitore_id=fornitore_id,
            sku_interno=sku,
            descrizione=desc,
            prezzo_pattuito=chosen_price,
            unita_misura=uom,
            data_inizio_validita=g["latest_date"] or today,
            data_scadenza=None,
            pfa_tipo=None,
            pfa_valore=None,
        )
        db.add(listino)

    await db.flush()

    return {
        "status": "ok",
        "fornitore": fornitore.nome_azienda,
        "total_extracted": len(grouped),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "message": f"Listino generato da fatture: {inserted} inseriti, {updated} aggiornati, {skipped} invariati.",
    }


@router.delete(
    "/fornitore/{fornitore_id}",
    summary="Elimina Listino Fornitore",
    description="Elimina tutti gli articoli a listino associati a un fornitore.",
)
async def delete_listino_fornitore(
    fornitore_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Verifica fornitore esiste
    from app.models.fornitori import Fornitore
    forn_result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = forn_result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
        
    # Elimina tutti gli articoli in listino per questo fornitore
    await db.execute(
        ListinoMaster.__table__.delete().where(ListinoMaster.fornitore_id == fornitore_id)
    )
    await db.commit()
    return {"detail": f"Listino del fornitore {fornitore.nome_azienda} eliminato con successo."}



@router.post(
    "/{listino_id}/aggiorna-prezzo",
    response_model=ListinoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Aggiorna prezzo (Append-Only)",
    description="Scadenza il record corrente e crea nuova versione — Spec §4.4",
)
async def aggiorna_prezzo_listino(
    listino_id: int,
    data: ListinoUpdate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Workflow Versioning Append-Only — Spec §4.4:
    1. Setta data_scadenza = OGGI sul record attuale
    2. Crea nuovo record con nuovo prezzo e data_inizio_validita = DOMANI
    3. Le fatture storiche continuano a puntare al record con il prezzo valido
    """
    # Trova record attuale
    result = await db.execute(
        select(ListinoMaster).where(
            and_(
                ListinoMaster.id == listino_id,
                ListinoMaster.data_scadenza.is_(None),
            )
        )
    )
    attuale = result.scalar_one_or_none()
    if not attuale:
        raise HTTPException(status_code=404, detail="Voce listino attiva non trovata")

    oggi = date.today()

    # Step 1: scadenza il record corrente
    attuale.data_scadenza = oggi

    # Step 2: crea nuova versione
    pfa_tipo_val = attuale.pfa_tipo
    pfa_valore_val = attuale.pfa_valore
    
    if data.pfa_tipo is not None:
        if data.pfa_tipo.lower() == "none" or data.pfa_tipo == "":
            pfa_tipo_val = None
            pfa_valore_val = None
        else:
            pfa_tipo_val = PFATipo(data.pfa_tipo)
            if data.pfa_valore is not None:
                pfa_valore_val = data.pfa_valore
    elif data.pfa_valore is not None:
        pfa_valore_val = data.pfa_valore

    nuovo = ListinoMaster(
        fornitore_id=attuale.fornitore_id,
        sku_interno=attuale.sku_interno,
        descrizione=attuale.descrizione,
        prezzo_pattuito=data.prezzo_pattuito or attuale.prezzo_pattuito,
        unita_misura=attuale.unita_misura,
        data_inizio_validita=data.data_inizio_validita or (oggi + timedelta(days=1)),
        data_scadenza=None,
        pfa_tipo=pfa_tipo_val,
        pfa_valore=pfa_valore_val,
    )
    db.add(nuovo)
    await db.flush()
    await db.refresh(nuovo)
    return nuovo


@router.get(
    "/{listino_id}",
    response_model=ListinoResponse,
    summary="Dettaglio voce listino",
)
async def get_listino(
    listino_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ListinoMaster).where(ListinoMaster.id == listino_id)
    )
    listino = result.scalar_one_or_none()
    if not listino:
        raise HTTPException(status_code=404, detail="Voce listino non trovata")
    return listino


@router.get(
    "/{listino_id}/storico",
    response_model=list[ListinoResponse],
    summary="Storico versioni prezzo",
)
async def get_storico_listino(
    listino_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mostra tutte le versioni di un SKU (append-only history)."""
    # Recupera il record per ottenere fornitore_id e sku_interno
    result = await db.execute(
        select(ListinoMaster).where(ListinoMaster.id == listino_id)
    )
    ref = result.scalar_one_or_none()
    if not ref:
        raise HTTPException(status_code=404, detail="Voce listino non trovata")

    # Trova tutte le versioni dello stesso SKU/fornitore
    result = await db.execute(
        select(ListinoMaster)
        .where(
            and_(
                ListinoMaster.fornitore_id == ref.fornitore_id,
                ListinoMaster.sku_interno == ref.sku_interno,
            )
        )
        .order_by(ListinoMaster.data_inizio_validita.desc())
    )
    return result.scalars().all()


# ─────────────────────────────────────────────
# PFA Scaglioni
# ─────────────────────────────────────────────

@router.post(
    "/{listino_id}/pfa-scaglioni",
    response_model=PFAScaglioneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Aggiungi scaglione PFA",
)
async def create_pfa_scaglione(
    listino_id: int,
    data: PFAScaglioneCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scaglione = PFAScaglione(
        listino_id=listino_id,
        soglia_da=data.soglia_da,
        soglia_a=data.soglia_a,
        valore_percentuale=data.valore_percentuale,
    )
    db.add(scaglione)
    await db.flush()
    await db.refresh(scaglione)
    return scaglione


@router.get(
    "/{listino_id}/pfa-scaglioni",
    response_model=list[PFAScaglioneResponse],
    summary="Lista scaglioni PFA",
)
async def list_pfa_scaglioni(
    listino_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PFAScaglione)
        .where(PFAScaglione.listino_id == listino_id)
        .order_by(PFAScaglione.soglia_da)
    )
    return result.scalars().all()


# ─────────────────────────────────────────────
# UoM Conversioni
# ─────────────────────────────────────────────

@router.post(
    "/{listino_id}/uom",
    response_model=UoMConversioneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Aggiungi conversione UoM",
)
async def create_uom_conversione(
    listino_id: int,
    data: UoMConversioneCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conversione = UoMConversione(
        listino_id=listino_id,
        uom_fattura=data.uom_fattura,
        coefficiente=data.coefficiente,
    )
    db.add(conversione)
    await db.flush()
    await db.refresh(conversione)
    return conversione


@router.get(
    "/{listino_id}/uom",
    response_model=list[UoMConversioneResponse],
    summary="Lista conversioni UoM",
)
async def list_uom_conversioni(
    listino_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UoMConversione)
        .where(UoMConversione.listino_id == listino_id)
    )
    return result.scalars().all()
