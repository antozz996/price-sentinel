"""
Price Sentinel — Listino Master Router.
CRUD Append-Only con versioning — Spec §4.4.
Include gestione PFA Scaglioni, UoM Conversioni, Import/Export Excel.
"""

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from jose import JWTError, jwt

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File, status
from fastapi.responses import Response
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.config import settings
from app.database import get_db
from app.models.listino import ListinoMaster, PFAScaglione, PFATipo, UoMConversione
from app.models.purchase_policy import SmartPriceSheetPreview
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


def _deny_ungoverned_contract_write(reason: str) -> None:
    """Fail closed until a reviewed, signed contract-approval flow exists."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{reason} Nessun prezzo concordato o dato storico è stato modificato. "
            "Usa l'anteprima e il percorso di approvazione autorizzato."
        ),
    )



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
    # API remains registered for compatibility, but direct contract writes are
    # forbidden until they require a reviewed and bound approval token.
    _deny_ungoverned_contract_write(
        "Creazione diretta del prezzo contrattuale disabilitata."
    )

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
    # The standard import remains useful for validation, but MUST NOT commit
    # directly. The comparative importer implements signed human approval.
    if not dry_run:
        _deny_ungoverned_contract_write(
            "Importazione listino standard senza approvazione disabilitata."
        )
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Formato non supportato. Usa un file .xlsx")
    from app.models.fornitori import Fornitore
    forn_result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = forn_result.scalar_one_or_none()
    if fornitore is None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    import io
    file_data = io.BytesIO(await file.read())
    parse_result = parse_listino_excel(file_data, fornitore_id)
    return {
        "mode": "dry_run" if parse_result.is_valid else "validation_failed",
        "fornitore": fornitore.nome_azienda,
        "warning": "Anteprima di sola lettura: per approvare prezzi usa il flusso comparativo con token.",
        **parse_result.to_dict(),
    }

@router.post(
    "/import-multi-supplier",
    summary="Importa Listino Comparativo Multi-Fornitore — approvazione obbligatoria",
    description=(
        "La prima chiamata restituisce una anteprima e un token firmato a scadenza. "
        "La conferma richiede token, file originale e approvazione esplicita. "
        "Chiamate di scrittura dirette senza token sono rifiutate."
    ),
)
async def import_multi_supplier(
    file: UploadFile = File(..., description="File Excel .xlsx comparativo"),
    dry_run: bool = Query(True, description="Anteprima obbligatoria; false solo con token valido"),
    approval_token: str | None = Form(None),
    confirm_import: bool = Form(False),
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import io
    from app.services.excel_import_multi import parse_multi_supplier_excel, generate_deterministic_piva
    from app.models.fornitori import Fornitore

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Formato non supportato. Usa .xlsx")

    # The legacy supplier/contract tables are global, without tenant_id.
    # Fail closed for secondary tenants until contracts become tenant-scoped.
    tenant_id = getattr(_admin, "tenant_id", None)
    if tenant_id != 1:
        raise HTTPException(status_code=403, detail="Import comparativo disponibile solo per azienda principale fino all'isolamento listini")

    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File superiore a 10 MB")
    digest = sha256(raw).hexdigest()
    parse_result = parse_multi_supplier_excel(io.BytesIO(raw))

    if not parse_result.is_valid:
        return {"mode": "validation_failed", **parse_result.to_dict()}
    # The admin must be able to review EVERY line, not only the first 50.
    if len(parse_result.records) > 2000:
        raise HTTPException(
            status_code=413,
            detail="Il file supera 2000 righe: suddividi il listino per consentire la revisione completa",
        )

    if dry_run:
        if approval_token or confirm_import:
            raise HTTPException(status_code=400, detail="Anteprima e conferma devono essere richieste separatamente")

        # Preview writes ONLY the control record. No supplier or contract changes.
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=15)
        preview = SmartPriceSheetPreview(
            id=uuid4(),
            payload_hash=digest,
            preview_payload={
                "purpose": "comparative_price_import_v1",
                "tenant_id": tenant_id,
                "file_sha256": digest,
                "total_rows": parse_result.total_rows,
                "suppliers_detected": parse_result.suppliers_detected,
            },
            status="ready",
            location_id=None,
            created_by=_admin.id,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(preview)
        await db.flush()
        token = jwt.encode(
            {
                "purpose": "comparative_price_import_v1",
                "jti": str(preview.id),
                "sub": str(_admin.id),
                "tid": tenant_id,
                "sha256": digest,
                "exp": int(expires_at.timestamp()),
            },
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        return {
            "mode": "dry_run",
            **parse_result.to_dict(),
            "records_preview": [
                {
                    "sku_interno": record["sku_interno"],
                    "descrizione": record["descrizione"],
                    "unita_misura": record["unita_misura"],
                    "prezzi": {supplier: str(price) for supplier, price in record["prezzi"].items()},
                }
                for record in parse_result.records
            ],
            "records_preview_truncated": False,
            "preview_token": token,
            "expires_at": expires_at.isoformat(),
            "warning": (
                "I nuovi fornitori vengono creati provvisori e disabilitati, "
                "con Partita IVA tecnica da verificare prima dell'attivazione commerciale. "
                "I nuovi prezzi partono oggi; le variazioni di accordi esistenti decorrono "
                "da domani per evitare sovrapposizioni nelle fatture datate oggi."
            ),
        }

    if not confirm_import or not isinstance(approval_token, str) or not approval_token:
        raise HTTPException(status_code=403, detail="Anteprima firmata e conferma obbligatorie")

    try:
        claims = jwt.decode(approval_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        preview_id = UUID(claims["jti"])
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Token di anteprima non valido o scaduto") from exc

    if (
        claims.get("purpose") != "comparative_price_import_v1"
        or claims.get("sub") != str(_admin.id)
        or claims.get("tid") != tenant_id
        or claims.get("sha256") != digest
    ):
        raise HTTPException(status_code=403, detail="Anteprima diversa da file, utente o azienda")

    # Serialize imports even when TWO DIFFERENT approved tokens overlap:
    # global, transaction-scoped lock for this V2 database, then the token row lock.
    # Without this, concurrent first-time supplier inserts can duplicate contracts.
    await db.execute(text("SELECT pg_advisory_xact_lock(481991, 2004)"))

    # Pessimistic row lock serializes simultaneous requests to spend a token.
    # The transaction commits atomically with supplier/price writes (get_db).
    preview = (await db.execute(
        select(SmartPriceSheetPreview)
        .where(SmartPriceSheetPreview.id == preview_id)
        .with_for_update()
    )).scalar_one_or_none()
    if (
        preview is None
        or preview.status != "ready"
        or preview.created_by != _admin.id
        or preview.payload_hash != digest
        or preview.preview_payload.get("purpose") != "comparative_price_import_v1"
        or preview.preview_payload.get("tenant_id") != tenant_id
        or preview.preview_payload.get("file_sha256") != digest
        or preview.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=403, detail="Anteprima scaduta, già approvata o non corrispondente")

    # Recheck validity and financial content against the approved preview.
    if (
        preview.preview_payload.get("total_rows") != parse_result.total_rows
        or preview.preview_payload.get("suppliers_detected") != parse_result.suppliers_detected
    ):
        raise HTTPException(status_code=403, detail="Contenuto differente dall'anteprima autorizzata")

    suppliers_map = {}
    for name in parse_result.suppliers_detected:
        stmt = select(Fornitore).where(func.lower(Fornitore.nome_azienda) == name.lower())
        forn = (await db.execute(stmt)).scalar_one_or_none()
        if not forn:
            piva = generate_deterministic_piva(name)
            forn = (await db.execute(
                select(Fornitore).where(Fornitore.partita_iva == piva)
            )).scalar_one_or_none()
            if forn and forn.nome_azienda.strip().casefold() != name.strip().casefold():
                raise HTTPException(
                    status_code=409,
                    detail="Identità fornitore ambigua: partita IVA tecnica già associata ad altro nome",
                )
            if not forn:
                # Never silently authorize synthetic VAT identities to receive orders.
                forn = Fornitore(
                    nome_azienda=name.upper(), partita_iva=piva, attivo_whitelist=False
                )
                db.add(forn)
                await db.flush()
        suppliers_map[name] = forn

    inserted = updated = skipped = 0
    today = date.today()
    for record in parse_result.records:
        for name, price in record["prezzi"].items():
            fornitore_id = suppliers_map[name].id
            existing_listino = (await db.execute(
                select(ListinoMaster).where(
                    ListinoMaster.fornitore_id == fornitore_id,
                    ListinoMaster.sku_interno == record["sku_interno"],
                    ListinoMaster.data_scadenza.is_(None),
                ).with_for_update()
            )).scalar_one_or_none()
            effective_date = today
            if existing_listino:
                if (
                    existing_listino.prezzo_pattuito == price
                    and existing_listino.unita_misura == record["unita_misura"]
                ):
                    skipped += 1
                    continue
                # Date-only contract history: the old price remains applicable
                # to invoices dated today; updated terms start tomorrow.
                # A second different change before an already-scheduled price
                # has begun would be ambiguous, so reject the entire import.
                if existing_listino.data_inizio_validita > today:
                    raise HTTPException(
                        status_code=409,
                        detail="Esiste già un aggiornamento con decorrenza futura: attendi la sua validità o richiedi una revisione contrattuale.",
                    )
                existing_listino.data_scadenza = today
                effective_date = today + timedelta(days=1)

            # Legacy contracts can already have overlapping date intervals.
            # Never silently insert another contract into an ambiguous interval.
            overlapping = (await db.execute(
                select(ListinoMaster.id).where(
                    ListinoMaster.fornitore_id == fornitore_id,
                    ListinoMaster.sku_interno == record["sku_interno"],
                    ListinoMaster.data_inizio_validita <= effective_date,
                    (ListinoMaster.data_scadenza.is_(None)) |
                    (ListinoMaster.data_scadenza >= effective_date),
                    *([ListinoMaster.id != existing_listino.id] if existing_listino else []),
                ).limit(1)
            )).scalar_one_or_none()
            if overlapping is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Intervalli di validità sovrapposti nello storico del prodotto: importazione bloccata per revisione.",
                )

            if existing_listino:
                updated += 1
            else:
                inserted += 1
            db.add(ListinoMaster(
                fornitore_id=fornitore_id,
                sku_interno=record["sku_interno"],
                descrizione=record["descrizione"],
                prezzo_pattuito=price,
                unita_misura=record["unita_misura"],
                data_inizio_validita=effective_date,
                data_scadenza=None,
                pfa_tipo=None,
                pfa_valore=None,
            ))

    preview.status = "committed"
    preview.committed_at = datetime.now(timezone.utc)
    preview.commit_result = {
        "inserted": inserted, "updated": updated,
        "skipped_duplicates": skipped,
    }
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
            Fattura.tipo_documento.in_([TipoDocumento.TD01, TipoDocumento.TD24, TipoDocumento.TD25]),
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
    # Invoiced prices are observations, NOT negotiated commercial terms.
    # The GET extract-from-invoices endpoint remains available for analysis.
    _deny_ungoverned_contract_write(
        "Importazione diretta da fatture disabilitata: un prezzo fatturato non prova un accordo."
    )

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
    # Historical prices are audit evidence referenced by invoice controls.
    # Hard deletion would silently destroy the economic record.
    _deny_ungoverned_contract_write(
        "Cancellazione fisica del listino e del suo storico disabilitata."
    )

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
    _deny_ungoverned_contract_write(
        "Aggiornamento manuale del prezzo senza approvazione disabilitato."
    )

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
