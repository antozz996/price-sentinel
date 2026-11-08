from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from hashlib import sha256
import secrets
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.supplier_price_form import SupplierPriceFormIdentity, SupplierPriceFormItem, SupplierPriceFormRequest
from app.models.utenti import Utente
from app.schemas.smart_price_sheet import VariantPricePreviewRequest, VariantPriceRow
from app.services.variant_price_import import build_variant_preview, commit_variant_preview

router = APIRouter()

ALLOWED_UNITS = {"KG", "G", "L", "CL", "ML", "PZ", "BT", "CT", "CF", "SC", "BX", "CONF"}


def _normalized_unit(value: str | None) -> str:
    unit = (value or "").strip().upper()
    if unit not in ALLOWED_UNITS:
        raise HTTPException(
            status_code=422,
            detail=f"Unità di misura non valida. Seleziona una tra: {', '.join(sorted(ALLOWED_UNITS))}",
        )
    return unit


# Fornitore.fatture/listini/alias are lazy="selectin": only scalar supplier
# columns are used here, so skip loading the whole invoice/price history.
_SUPPLIER_COLLECTIONS_NOLOAD = (noload(Fornitore.fatture), noload(Fornitore.listini), noload(Fornitore.alias))


def _needs_supplier_details(supplier: Fornitore | None) -> bool:
    # A supplier created from the forms page has only a provisional TEMP id:
    # the form asks for its real company name, VAT number and order phone.
    return bool(supplier) and (supplier.partita_iva or "").upper().startswith("TEMP")


def _clean_vat(value: str) -> str:
    vat = re.sub(r"\s+", "", value or "").upper()
    if vat.startswith("IT"):
        vat = vat[2:]
    if not re.fullmatch(r"\d{11}", vat):
        raise HTTPException(status_code=422, detail="La partita IVA deve avere 11 cifre")
    return vat


def _clean_phone(value: str) -> str:
    phone = " ".join((value or "").split())
    if not re.fullmatch(r"[0-9+()/\- ]{6,30}", phone) or len(re.sub(r"\D", "", phone)) < 8:
        raise HTTPException(status_code=422, detail="Numero di telefono per gli ordini non valido")
    return phone


def _require_primary_tenant(user: Utente) -> None:
    # Supplier and contract records are currently global legacy tables.
    if getattr(user, "tenant_id", None) != 1:
        raise HTTPException(status_code=403, detail="Moduli listino non ancora disponibili per questa azienda")


def _offer_id(supplier_id: int, sku: str, offer: "SupplierOffer") -> str:
    # Price and validity are deliberately excluded: a monthly price change
    # updates the same commercial package instead of creating a new identity.
    identity = "|".join((
        str(supplier_id), sku.strip().casefold(),
        re.sub(r"\s+", " ", (offer.dicitura_fornitore or "").strip().casefold()),
        re.sub(r"\s+", " ", (offer.marca or "").strip().casefold()),
        str(offer.quantita_confezione.normalize()) if offer.quantita_confezione else "",
        (offer.unita_misura or "").strip().casefold(),
    ))
    return "OFF-" + sha256(identity.encode("utf-8")).hexdigest()[:16].upper()


_PACK_UNIT_BY_COMPARISON = {"pz": "PZ", "piece": "PZ", "ct": "CT", "bt": "BT", "bottle": "BT", "cf": "CF"}
OfferFormat = tuple[Decimal | None, str | None, str | None, str | None]  # quantity, unit, wording, brand


async def _offer_formats(db: AsyncSession, supplier_id: int, rows: list[ListinoMaster]) -> dict[int, OfferFormat]:
    """Format of the agreed offer behind each listino row.

    Approved form offers are stored with unita_misura "conf" and the package on
    the alias, so the format is read back from the approved form (exact) or
    rebuilt from the alias, never shown to the supplier as "conf".
    """
    alias_ids = {row.supplier_product_alias_id for row in rows if row.supplier_product_alias_id}
    skus = {row.sku_interno for row in rows}
    aliases = {alias.id: alias for alias in (await db.execute(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.id.in_(alias_ids))
    )).scalars()} if alias_ids else {}
    products = {product.sku_interno: product for product in (await db.execute(
        select(Product).where(Product.sku_interno.in_(skus))
    )).scalars()} if alias_ids else {}
    approved: dict[str, dict] = {}
    if alias_ids:
        items = (await db.execute(
            select(SupplierPriceFormItem).join(SupplierPriceFormRequest).where(
                SupplierPriceFormRequest.supplier_id == supplier_id,
                SupplierPriceFormRequest.status == "approved",
                SupplierPriceFormItem.sku_interno.in_(skus),
            ).order_by(SupplierPriceFormRequest.id)
        )).scalars().all()
        for item in items:  # later approvals win
            for offer in item.offerte_inviate or []:
                approved[offer["id_offerta"]] = offer
    formats: dict[int, OfferFormat] = {}
    for row in rows:
        alias = aliases.get(row.supplier_product_alias_id)
        if alias is None:
            unit = (row.unita_misura or "").strip().upper()
            formats[row.id] = (None, unit if unit in ALLOWED_UNITS and unit != "CONF" else None, None, None)
            continue
        offer = approved.get(alias.supplier_code)
        if offer:
            formats[row.id] = (Decimal(offer["quantita_confezione"]), offer["unita_misura"],
                               offer.get("dicitura_fornitore"), offer.get("marca"))
            continue
        product = products.get(row.sku_interno)
        if alias.weight_g:
            quantity, unit = Decimal(alias.weight_g) / 1000, "KG"
        elif alias.volume_ml:
            quantity, unit = Decimal(alias.volume_ml) / 1000, "L"
        elif alias.pack_qty:
            quantity = Decimal(alias.pack_qty)
            unit = _PACK_UNIT_BY_COMPARISON.get((product.comparison_unit or "").strip().lower()) if product else None
        else:
            quantity, unit = None, None
        formats[row.id] = (quantity if unit else None, unit, alias.raw_description, alias.brand)
    return formats


def _format_label(quantity: Decimal | None, unit: str | None) -> str:
    if not unit:
        return "unità da completare"
    if quantity is None or quantity == 1:
        return unit
    return f"{format(quantity.normalize(), 'f').replace('.', ',')} {unit}"


def _request_view(request: SupplierPriceFormRequest) -> dict:
    return {
        "id": request.id,
        "supplier_id": request.supplier_id,
        "supplier_name": request.supplier.nome_azienda if request.supplier else None,
        "status": request.status,
        "request_type": request.request_type,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "submitted_at": request.submitted_at.isoformat() if request.submitted_at else None,
        "note": request.note,
        "validita_inviata_da": request.validita_inviata_da.isoformat() if request.validita_inviata_da else None,
        "validita_inviata_a": request.validita_inviata_a.isoformat() if request.validita_inviata_a else None,
        "requires_supplier_details": _needs_supplier_details(request.supplier),
        "anagrafica_inviata": {
            "ragione_sociale": request.identity.ragione_sociale,
            "partita_iva": request.identity.partita_iva,
            "telefono_ordini": request.identity.telefono_ordini,
        } if request.identity else None,
        "items": [
            {
                "id": item.id,
                "listino_id": item.listino_id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente) if item.prezzo_corrente is not None else None,
                "unita_corrente": item.unita_corrente,
                "quantita_corrente": str(item.quantita_corrente) if item.quantita_corrente is not None else None,
                "dicitura_corrente": item.dicitura_corrente,
                "brand_corrente": item.brand_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat() if item.validita_corrente_da else None,
                "validita_corrente_a": item.validita_corrente_a.isoformat() if item.validita_corrente_a else None,
                "prezzo_inviato": str(item.prezzo_inviato) if item.prezzo_inviato is not None else None,
                "unita_inviata": item.unita_inviata,
                "brand_inviata": item.brand_inviata,
                "dicitura_inviata": item.dicitura_inviata,
                "quantita_inviata": str(item.quantita_inviata) if item.quantita_inviata is not None else None,
                "conferma_prezzo": item.conferma_prezzo,
                "nota_fornitore": item.nota_fornitore,
                "non_trattato": item.non_trattato,
                "offerte_inviate": item.offerte_inviate or [],
                "esito": (
                    "non_trattato" if item.non_trattato
                    else "da_compilare" if item.prezzo_inviato is None
                    else "nuova_offerta" if request.request_type == "new_listino"
                    else "confermato" if item.conferma_prezzo
                    else "proposta_variazione"
                ),
            }
            for item in request.items
        ],
    }


class CreateFormRequest(BaseModel):
    supplier_id: int
    request_type: Literal["confirmation", "new_listino"] = "confirmation"
    listino_ids: list[int] = Field(default_factory=list, max_length=2000)
    product_ids: list[int] = Field(default_factory=list, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=100)
    expires_in_days: int = Field(default=14, ge=1, le=30)
    note: Optional[str] = Field(default=None, max_length=1000)


class SupplierOffer(BaseModel):
    prezzo: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=4)
    unita_misura: str | None = Field(default=None, min_length=1, max_length=50)
    marca: str | None = Field(default=None, max_length=100)
    dicitura_fornitore: str | None = Field(default=None, max_length=255)
    quantita_confezione: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=3)
    conferma_prezzo: bool = False
    nota: Optional[str] = Field(default=None, max_length=1000)


class SupplierAnswer(SupplierOffer):
    item_id: int
    non_trattato: bool = False
    offerte: list[SupplierOffer] | None = Field(default=None, min_length=1, max_length=10)


class SupplierDetails(BaseModel):
    ragione_sociale: str = Field(min_length=2, max_length=255)
    partita_iva: str = Field(min_length=11, max_length=20)
    telefono_ordini: str = Field(min_length=6, max_length=50)


class PublicSubmission(BaseModel):
    answers: list[SupplierAnswer] = Field(min_length=1, max_length=2000)
    # Required only for a new supplier with a provisional record.
    anagrafica: SupplierDetails | None = None
    # Optional for compatibility with supplier pages opened before this release.
    validita_inviata_da: date | None = None
    validita_inviata_a: date | None = None


@router.get("/public/{token}", summary="Visualizza il modulo listino del fornitore")
async def get_public_form(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    if len(token) < 40 or len(token) > 100:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier).options(*_SUPPLIER_COLLECTIONS_NOLOAD), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.token_hash == token_hash)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not request or request.status != "open" or request.expires_at <= now:
        raise HTTPException(status_code=404, detail="Link non valido, scaduto o già inviato")
    skus = {item.sku_interno for item in request.items}
    notes_by_sku = dict((await db.execute(
        select(Product.sku_interno, Product.supplier_form_note)
        .where(Product.sku_interno.in_(skus), Product.supplier_form_note.is_not(None))
    )).all()) if skus else {}
    return {
        "supplier_name": request.supplier.nome_azienda,
        "requires_supplier_details": _needs_supplier_details(request.supplier),
        "request_type": request.request_type,
        "expires_at": request.expires_at.isoformat(),
        "note": request.note,
        "items": [
            {
                "id": item.id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente) if item.prezzo_corrente is not None else None,
                "unita_corrente": item.unita_corrente,
                "quantita_corrente": str(item.quantita_corrente) if item.quantita_corrente is not None else None,
                "dicitura_corrente": item.dicitura_corrente,
                "brand_corrente": item.brand_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat() if item.validita_corrente_da else None,
                "validita_corrente_a": item.validita_corrente_a.isoformat() if item.validita_corrente_a else None,
                "istruzioni": notes_by_sku.get(item.sku_interno),
            }
            for item in request.items
        ],
    }


@router.post("/public/{token}/submit", summary="Invia la conferma o la proposta del fornitore")
async def submit_public_form(
    token: str,
    payload: PublicSubmission,
    db: AsyncSession = Depends(get_db),
):
    if len(token) < 40 or len(token) > 100:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.items), selectinload(SupplierPriceFormRequest.supplier).options(*_SUPPLIER_COLLECTIONS_NOLOAD))
        .where(SupplierPriceFormRequest.token_hash == token_hash)
        .with_for_update()
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not request or request.status != "open" or request.expires_at <= now:
        raise HTTPException(status_code=404, detail="Link non valido, scaduto o già inviato")
    details = None
    if _needs_supplier_details(request.supplier):
        if payload.anagrafica is None:
            raise HTTPException(status_code=422, detail="Indica ragione sociale, partita IVA e telefono per gli ordini")
        name = " ".join(payload.anagrafica.ragione_sociale.split())
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="Indica la ragione sociale")
        details = (name, _clean_vat(payload.anagrafica.partita_iva), _clean_phone(payload.anagrafica.telefono_ordini))
    if payload.validita_inviata_da is None:
        raise HTTPException(status_code=422, detail="Indica la data di inizio dell'offerta")
    if (
        payload.validita_inviata_da
        and payload.validita_inviata_a
        and payload.validita_inviata_a < payload.validita_inviata_da
    ):
        raise HTTPException(status_code=422, detail="La data di fine validità deve essere successiva o uguale alla data di inizio")

    answers_by_id = {answer.item_id: answer for answer in payload.answers}
    if len(answers_by_id) != len(payload.answers):
        raise HTTPException(status_code=422, detail="Il modulo contiene righe duplicate")
    expected_ids = {item.id for item in request.items}
    if set(answers_by_id) != expected_ids:
        raise HTTPException(status_code=422, detail="Compila tutte le righe del modulo senza modificarne l'identità")

    for item in request.items:
        answer = answers_by_id[item.id]
        if answer.non_trattato:
            if answer.conferma_prezzo or answer.offerte:
                raise HTTPException(status_code=422, detail="Un prodotto non trattato non può essere confermato")
            item.non_trattato = True
            item.prezzo_inviato = None
            item.unita_inviata = None
            item.brand_inviata = None
            item.dicitura_inviata = None
            item.quantita_inviata = None
            item.conferma_prezzo = False
            item.offerte_inviate = []
            continue
        offers = answer.offerte or [answer]
        saved_offers = []
        seen_offer_ids: set[str] = set()
        for index, offer in enumerate(offers):
            # Brand and supplier wording are optional (fresh produce): wording falls back to our description.
            if not (offer.dicitura_fornitore or "").strip():
                offer.dicitura_fornitore = item.descrizione[:255]
            if offer.prezzo is None or not (offer.unita_misura or "").strip() or offer.quantita_confezione is None:
                raise HTTPException(status_code=422, detail=f"Completa quantità, unità e prezzo dell'offerta {index + 1} per {item.sku_interno}")
            brand = (offer.marca or "").strip() or None
            unit = _normalized_unit(offer.unita_misura)
            if request.request_type == "new_listino" and offer.conferma_prezzo:
                raise HTTPException(status_code=422, detail="Una nuova offerta non può essere marcata come conferma")
            if offer.conferma_prezzo and index != 0:
                raise HTTPException(status_code=422, detail="Solo l'offerta principale può confermare il prezzo pattuito")
            if offer.conferma_prezzo and not (
                item.prezzo_corrente is not None and offer.prezzo == item.prezzo_corrente
                and item.unita_corrente is not None and unit.casefold() == item.unita_corrente.strip().casefold()
                and (item.quantita_corrente is None or offer.quantita_confezione == item.quantita_corrente)
            ):
                raise HTTPException(status_code=422, detail=f"La riga {item.sku_interno} è indicata come confermata ma prezzo, quantità o unità sono diversi dal pattuito")
            offer_id = _offer_id(request.supplier_id, item.sku_interno, offer)
            if offer_id in seen_offer_ids:
                raise HTTPException(status_code=422, detail=f"Due offerte identiche per {item.sku_interno}: cambia marca, formato o dicitura")
            seen_offer_ids.add(offer_id)
            saved_offers.append({
                "id_offerta": offer_id,
                "prezzo": str(offer.prezzo),
                "unita_misura": unit,
                "marca": brand,
                "dicitura_fornitore": offer.dicitura_fornitore.strip(),
                "quantita_confezione": str(offer.quantita_confezione),
                "conferma_prezzo": offer.conferma_prezzo,
                "nota": offer.nota.strip() if offer.nota else None,
            })
        primary = offers[0]
        item.non_trattato = False
        item.prezzo_inviato = primary.prezzo
        item.unita_inviata = _normalized_unit(primary.unita_misura)
        item.brand_inviata = (primary.marca or "").strip() or None
        item.dicitura_inviata = primary.dicitura_fornitore.strip()
        item.quantita_inviata = primary.quantita_confezione
        item.nota_fornitore = primary.nota.strip() if primary.nota else None
        item.conferma_prezzo = primary.conferma_prezzo
        item.offerte_inviate = saved_offers

    if details:
        # Kept with the response; written to the supplier record only on approval.
        db.add(SupplierPriceFormIdentity(
            request_id=request.id, ragione_sociale=details[0], partita_iva=details[1],
            telefono_ordini=details[2], created_at=now,
        ))
    request.status = "submitted"
    request.submitted_at = now
    request.validita_inviata_da = payload.validita_inviata_da
    request.validita_inviata_a = payload.validita_inviata_a
    await db.commit()
    message = (
        "Nuova offerta inviata con validità indicata. È in attesa di revisione; nessun prezzo ufficiale è stato modificato."
        if request.request_type == "new_listino"
        else "Risposta inviata con il periodo di validità indicato. Nessun prezzo nel listino master è stato modificato."
    )
    return {"status": "submitted", "message": message}


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Crea un modulo per un fornitore")
async def create_form_request(
    payload: CreateFormRequest,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    supplier = await db.get(Fornitore, payload.supplier_id, options=_SUPPLIER_COLLECTIONS_NOLOAD)
    if not supplier or supplier.archived_at is not None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o archiviato")

    if payload.request_type == "new_listino":
        if not payload.category or not payload.product_ids or payload.listino_ids:
            raise HTTPException(status_code=422, detail="Per una nuova richiesta indica categoria e prodotti, senza righe listino esistenti")
        if len(set(payload.product_ids)) != len(payload.product_ids):
            raise HTTPException(status_code=422, detail="La selezione contiene prodotti duplicati")
        products = (await db.execute(
            select(Product)
            .where(
                Product.id.in_(payload.product_ids),
                func.lower(Product.category) == payload.category.strip().lower(),
                Product.is_active.is_(True),
            )
            .order_by(Product.canonical_name)
        )).scalars().all()
        if len(products) != len(payload.product_ids):
            raise HTTPException(status_code=422, detail="Uno o più prodotti non appartengono alla categoria selezionata o non sono attivi")
        form_items = [
            SupplierPriceFormItem(
                listino_id=None,
                sku_interno=product.sku_interno or f"PROD-{product.id}",
                descrizione=product.canonical_name,
                prezzo_corrente=None,
                unita_corrente=product.comparison_unit,
                brand_corrente=product.brand,
                validita_corrente_da=None,
                validita_corrente_a=None,
            )
            for product in products
        ]
    else:
        if not payload.listino_ids or payload.product_ids or payload.category:
            raise HTTPException(status_code=422, detail="Per confermare un listino seleziona solo le sue righe attive")
        if len(set(payload.listino_ids)) != len(payload.listino_ids):
            raise HTTPException(status_code=422, detail="La selezione contiene righe duplicate")
        today = datetime.now(ZoneInfo("Europe/Rome")).date()
        rows = (await db.execute(
            select(ListinoMaster)
            .where(
                ListinoMaster.id.in_(payload.listino_ids),
                ListinoMaster.fornitore_id == payload.supplier_id,
                ListinoMaster.data_inizio_validita <= today,
                (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= today),
            )
            .order_by(ListinoMaster.sku_interno)
        )).scalars().all()
        if len(rows) != len(payload.listino_ids):
            raise HTTPException(
                status_code=422,
                detail="Una o più righe non appartengono al fornitore o non sono attive oggi",
            )
        sku_values = {row.sku_interno for row in rows if row.sku_interno}
        products = (await db.execute(select(Product).where(Product.sku_interno.in_(sku_values)))).scalars().all() if sku_values else []
        brand_by_sku = {product.sku_interno: product.brand for product in products}
        formats = await _offer_formats(db, payload.supplier_id, rows)
        form_items = [
            SupplierPriceFormItem(
                listino_id=row.id,
                sku_interno=row.sku_interno,
                descrizione=row.descrizione,
                prezzo_corrente=row.prezzo_pattuito,
                unita_corrente=formats[row.id][1],
                quantita_corrente=formats[row.id][0],
                dicitura_corrente=formats[row.id][2],
                brand_corrente=formats[row.id][3] or brand_by_sku.get(row.sku_interno),
                validita_corrente_da=row.data_inizio_validita,
                validita_corrente_a=row.data_scadenza,
            )
            for row in rows
        ]

    token = secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc)
    request = SupplierPriceFormRequest(
        supplier_id=supplier.id,
        created_by_id=admin.id,
        request_type=payload.request_type,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
        status="open",
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
        note=payload.note.strip() if payload.note else None,
        items=form_items,
    )
    db.add(request)
    await db.commit()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier).options(*_SUPPLIER_COLLECTIONS_NOLOAD), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request.id)
    )).scalar_one()
    return {
        "request": _request_view(request),
        "token": token,
        "public_path": f"/fornitore/listino/{token}",
    }


class NewSupplierRequest(BaseModel):
    nome: str = Field(min_length=2, max_length=255)
    categories: list[Literal["Food", "Beverage", "Materiali"]] = Field(min_length=1, max_length=3)


@router.post("/new-supplier", status_code=status.HTTP_201_CREATED,
             summary="Crea un fornitore provvisorio da invitare con il modulo")
async def create_provisional_supplier(
    payload: NewSupplierRequest,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """The supplier sends company name, VAT number and order phone in the form."""
    from app.models.purchase_policy import SupplierCategoryCapability

    _require_primary_tenant(admin)
    name = " ".join(payload.nome.split())
    existing = await db.scalar(select(Fornitore).where(
        func.lower(func.btrim(Fornitore.nome_azienda)) == name.casefold(),
        Fornitore.archived_at.is_(None),
    ))
    if existing:
        raise HTTPException(status_code=409, detail=f"Esiste già un fornitore chiamato {existing.nome_azienda}")
    # TEMP marks an internal provisional id, never a claimed VAT number.
    supplier = Fornitore(nome_azienda=name, partita_iva="TEMP" + secrets.token_hex(8).upper(), attivo_whitelist=True)
    db.add(supplier)
    await db.flush()
    now = datetime.now(timezone.utc)
    for category in sorted(set(payload.categories)):
        db.add(SupplierCategoryCapability(
            supplier_id=supplier.id, category=category, enabled=True,
            reason="Nuovo fornitore creato da Moduli fornitori",
            created_by=admin.id, updated_by=admin.id, created_at=now, updated_at=now,
        ))
    await db.commit()
    return {"id": supplier.id, "nome_azienda": supplier.nome_azienda, "telefono_contatto": None}


@router.get("/catalog-products", summary="Elenca i prodotti attivi del catalogo per una nuova richiesta listino")
async def get_catalog_products(
    category: str = Query(min_length=1, max_length=100),
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    products = (await db.execute(
        select(Product)
        .where(func.lower(Product.category) == category.strip().lower(), Product.is_active.is_(True))
        .order_by(Product.canonical_name)
    )).scalars().all()
    return [
        {
            "id": product.id,
            "sku_interno": product.sku_interno or f"PROD-{product.id}",
            "descrizione": product.canonical_name,
            "unita_misura": product.comparison_unit,
            "category": product.category,
            "subcategory": product.subcategory,
        }
        for product in products
    ]


@router.get("/catalog/{supplier_id}", summary="Elenca il listino del fornitore raggruppato per categoria")
async def get_supplier_catalog(
    supplier_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    supplier = await db.get(Fornitore, supplier_id, options=_SUPPLIER_COLLECTIONS_NOLOAD)
    if not supplier or supplier.archived_at is not None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o archiviato")

    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    rows = (await db.execute(
        select(ListinoMaster)
        .where(
            ListinoMaster.fornitore_id == supplier_id,
            ListinoMaster.data_inizio_validita <= today,
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= today),
        )
        .order_by(ListinoMaster.sku_interno)
    )).scalars().all()
    # Same rule as order resolution: once a product has approved offers from this
    # supplier, the older generic row (no offer) is superseded and not re-asked.
    offer_skus = {row.sku_interno for row in rows if row.supplier_product_alias_id}
    rows = [row for row in rows if row.supplier_product_alias_id or row.sku_interno not in offer_skus]
    formats = await _offer_formats(db, supplier_id, rows)

    categories_by_sku: dict[str, tuple[str | None, str | None]] = {}
    sku_values = {row.sku_interno for row in rows if row.sku_interno}
    if sku_values:
        products = (await db.execute(
            select(Product.sku_interno, Product.category, Product.subcategory)
            .where(Product.sku_interno.in_(sku_values), Product.is_active.is_(True))
            .order_by(Product.id.desc())
        )).all()
        for sku, category, subcategory in products:
            categories_by_sku.setdefault(sku, (category, subcategory))

    return [
        {
            "id": row.id,
            "sku_interno": row.sku_interno,
            "descrizione": row.descrizione + (f" · {formats[row.id][3]}" if formats[row.id][3] else ""),
            "prezzo_pattuito": str(row.prezzo_pattuito),
            "unita_misura": _format_label(formats[row.id][0], formats[row.id][1]),
            "data_inizio_validita": row.data_inizio_validita.isoformat(),
            "data_scadenza": row.data_scadenza.isoformat() if row.data_scadenza else None,
            "category": categories_by_sku.get(row.sku_interno, (None, None))[0],
            "subcategory": categories_by_sku.get(row.sku_interno, (None, None))[1],
        }
        for row in rows
    ]


@router.get("/", summary="Elenca i moduli listino")
async def list_form_requests(
    status_filter: str = Query(default="all", pattern="^(all|open|submitted|approved|rejected|expired|closed)$"),
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    query = (
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier).options(*_SUPPLIER_COLLECTIONS_NOLOAD), selectinload(SupplierPriceFormRequest.items))
        .order_by(SupplierPriceFormRequest.created_at.desc())
    )
    records = (await db.execute(query)).scalars().unique().all()
    now = datetime.now(timezone.utc)
    result = []
    for request in records:
        # Expire first, so an overdue link is listed as expired, not as open.
        if request.status == "open" and request.expires_at <= now:
            request.status = "expired"
        if status_filter != "all" and request.status != status_filter:
            continue
        result.append(_request_view(request))
    await db.commit()
    return result


@router.get("/notifications/pending", summary="Conta le risposte dei fornitori da revisionare")
async def pending_supplier_form_notifications(
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    count = await db.scalar(select(func.count(SupplierPriceFormRequest.id)).where(
        SupplierPriceFormRequest.status == "submitted"
    ))
    return {"pending_count": int(count or 0)}


@router.post("/{request_id}/approve", summary="Approva e integra la risposta nel listino V2")
async def approve_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request_id)
        .with_for_update()
    )).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status != "submitted":
        raise HTTPException(status_code=409, detail="La risposta non è più in attesa di approvazione")
    if not request.validita_inviata_da:
        raise HTTPException(status_code=422, detail="La risposta non indica la data di inizio validità")

    products = (await db.execute(select(Product).where(
        Product.sku_interno.in_({item.sku_interno for item in request.items}),
        Product.is_active.is_(True),
    ))).scalars().all()
    products_by_sku = {product.sku_interno: product for product in products}
    rows: list[VariantPriceRow] = []
    for item in request.items:
        if item.non_trattato:
            continue
        product = products_by_sku.get(item.sku_interno)
        if not product:
            raise HTTPException(status_code=409, detail=f"Prodotto {item.sku_interno} non più disponibile")
        for offer in item.offerte_inviate or []:
            rows.append(VariantPriceRow(
                product_id=product.id,
                supplier_id=request.supplier_id,
                sku=item.sku_interno,
                offer_id=offer["id_offerta"],
                description=offer["dicitura_fornitore"],
                brand=offer.get("marca"),
                quantity=Decimal(offer["quantita_confezione"]),
                unit=_normalized_unit(offer.get("unita_misura")),
                price=Decimal(offer["prezzo"]),
                package_confirmed=True,
            ))
    if not rows:
        raise HTTPException(status_code=422, detail="La risposta non contiene offerte da integrare")

    preview = await build_variant_preview(db, VariantPricePreviewRequest(
        rows=rows, effective_date=request.validita_inviata_da
    ), admin.id)
    errors = preview.preview_payload.get("errors") or []
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(error["message"] for error in errors))
    identity = await db.get(SupplierPriceFormIdentity, request.id)
    if identity:
        supplier = await db.get(Fornitore, request.supplier_id, options=_SUPPLIER_COLLECTIONS_NOLOAD)
        if _needs_supplier_details(supplier):
            clash = await db.scalar(select(Fornitore).options(*_SUPPLIER_COLLECTIONS_NOLOAD).where(
                Fornitore.id != supplier.id,
                Fornitore.partita_iva.in_([identity.partita_iva, "IT" + identity.partita_iva]),
            ))
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"La partita IVA {identity.partita_iva} è già registrata per {clash.nome_azienda}: "
                           "rifiuta la risposta o unisci prima i due fornitori",
                )
            supplier.nome_azienda = identity.ragione_sociale
            supplier.partita_iva = identity.partita_iva
            supplier.telefono_contatto = identity.telefono_ordini
    result = await commit_variant_preview(db, preview)
    if request.validita_inviata_a and result.get("listino_ids"):
        approved_rows = (await db.execute(select(ListinoMaster).where(
            ListinoMaster.id.in_(result["listino_ids"])
        ))).scalars().all()
        for row in approved_rows:
            row.data_scadenza = request.validita_inviata_a
    request.status = "approved"
    await db.commit()
    return {"id": request.id, "status": request.status, "result": result}


@router.post("/{request_id}/reject", summary="Rifiuta una risposta del fornitore")
async def reject_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(select(SupplierPriceFormRequest).where(
        SupplierPriceFormRequest.id == request_id
    ).with_for_update())).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status != "submitted":
        raise HTTPException(status_code=409, detail="La risposta non è più in attesa di revisione")
    request.status = "rejected"
    await db.commit()
    return {"id": request.id, "status": request.status}


@router.get("/{request_id}", summary="Dettaglio risposta a un modulo listino")
async def get_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier).options(*_SUPPLIER_COLLECTIONS_NOLOAD), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request_id)
    )).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status == "open" and request.expires_at <= datetime.now(timezone.utc):
        request.status = "expired"
        await db.commit()
    return _request_view(request)


@router.post("/{request_id}/close", summary="Chiude un modulo listino")
async def close_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(select(SupplierPriceFormRequest).where(SupplierPriceFormRequest.id == request_id).with_for_update())).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status not in {"open", "submitted", "expired"}:
        raise HTTPException(status_code=409, detail="Modulo già chiuso")
    request.status = "closed"
    await db.commit()
    return {"id": request.id, "status": request.status}


@router.delete("/{request_id}", status_code=status.HTTP_200_OK, summary="Elimina un modulo listino e revoca il link")
async def delete_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request_id)
        .with_for_update()
    )).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status == "approved":
        # An approved response is the audit trail of prices now in the price list.
        raise HTTPException(
            status_code=409,
            detail="Un modulo approvato non si può eliminare: è la traccia dei prezzi entrati nel listino",
        )

    # Removing the request cascades to its response snapshot items and revokes
    # the public token. It never alters the referenced official listino rows.
    await db.delete(request)
    await db.commit()
    return {"id": request_id, "deleted": True}

