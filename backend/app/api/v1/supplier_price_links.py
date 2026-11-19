"""Listino sempre aperto: link fisso con cui il fornitore aggiorna i prezzi.

Il fornitore vede i suoi prezzi validi oggi (i 50 su cui spendiamo di più in alto)
e cambia solo il prezzo: dicitura, marca, formato e unità restano quelli concordati.
Ogni modifica diventa una SupplierPriceChange con la sua decorrenza (regole in
services/open_price_list_rules.py); il listino viene aggiornato dal job di attivazione.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import require_admin
from app.api.v1.supplier_price_forms import (
    _active_supplier_rows,
    _best_prices,
    _encrypt_token,
    _format_label,
    _offer_formats,
    _check_quantity,
    _require_primary_tenant,
    _token_cipher,
)
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ORIGINE_LISTINO_APERTO, ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.supplier_price_form import SupplierPriceFormRequest
from app.schemas.smart_price_sheet import VariantPricePreviewRequest, VariantPriceRow
from app.models.supplier_price_link import (
    STATI_IN_ATTESA,
    STATO_APPLICATO,
    PROPOSTA_APPROVATA,
    PROPOSTA_IN_ATTESA,
    PROPOSTA_NOME,
    PROPOSTA_PRODOTTO_NUOVO,
    PROPOSTA_RIFIUTATA,
    PROPOSTA_SOSTITUITA,
    PROPOSTA_UNITA,
    STATO_PROGRAMMATO,
    STATO_RIFIUTATO,
    STATO_SOSTITUITO,
    STATO_TRATTENUTO,
    TIPO_AUMENTO,
    TIPO_RIBASSO,
    UNITA_CON_CONTENUTO,
    UNITA_CONTENUTO,
    UNITA_VENDITA,
    SupplierPriceChange,
    SupplierPriceLink,
    SupplierProductAbsence,
    SupplierProductProposal,
    offer_key,
)
from app.services.open_price_list_sector import sector_products, skus_in_use
from app.services.normalization import normalize_text
from app.models.utenti import Utente
from app.services.open_price_list_activation import _newer_row_exists, apply_change_now
from app.services.open_price_list_forecast import Forecast, forecast_on
from app.services.open_price_list_rules import (
    ROME,
    annual_impact,
    decide_change,
    next_fixed_date,
    offer_lock_key,
    previous_fixed_date,
    reminder_deadline,
    today_rome,
)
from app.services.purchase_lines import purchase_lines_select
from app.services.variant_price_import import build_variant_preview, commit_variant_preview
from app.services.smart_price_purchases import load_purchase_stats_select

router = APIRouter()

TOP_PRODUCTS = 50
RIBASSI_GIORNI = 30
NON_CONFERMATO_GIORNI = 30
# I moduli fornitori esistono solo per la prima azienda: la spesa si legge sulle sue fatture.
_PRIMARY_TENANT = SimpleNamespace(tenant_id=1)


def _hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _link_token(link: SupplierPriceLink) -> str | None:
    if not link.token_encrypted:
        return None
    try:
        token = _token_cipher().decrypt(link.token_encrypted.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    return token if _hash(token) == link.token_hash else None


async def _active_link(db: AsyncSession, token: str, *, for_update: bool = False) -> tuple[SupplierPriceLink, str]:
    if not 40 <= len(token) <= 100:
        raise HTTPException(status_code=404, detail="Link non valido")
    stmt = select(SupplierPriceLink).options(noload("*")).where(
        SupplierPriceLink.token_hash == _hash(token), SupplierPriceLink.attivo.is_(True))
    if for_update:
        stmt = stmt.with_for_update()
    link = (await db.execute(stmt)).scalar_one_or_none()
    supplier = await db.get(Fornitore, link.fornitore_id, options=[noload("*")]) if link else None
    if not link or not supplier or supplier.archived_at or not supplier.attivo_whitelist:
        raise HTTPException(status_code=404, detail="Link non valido o disattivato")
    return link, supplier.nome_azienda


async def _spend_by_sku(db: AsyncSession, skus: set[str], today) -> dict[str, Decimal]:
    if not skus:
        return {}
    stats = await load_purchase_stats_select(db, _PRIMARY_TENANT, skus=skus, date_from=today - timedelta(days=365))
    return {row.sku_interno: Decimal(str(row.spesa or 0)) for row in (await db.execute(stats)).all()}


async def _pending_changes(db: AsyncSession, fornitore_id: int) -> dict[str, SupplierPriceChange]:
    rows = (await db.execute(select(SupplierPriceChange).where(
        SupplierPriceChange.fornitore_id == fornitore_id,
        SupplierPriceChange.stato.in_(STATI_IN_ATTESA),
    ))).scalars().all()
    return {change.chiave_offerta: change for change in rows}


def _money(value) -> str | None:
    return None if value is None else str(Decimal(str(value)))


async def _spend_by_supplier_sku(db: AsyncSession, skus: set[str], today) -> dict[tuple[int, str], Decimal]:
    """Spesa netta degli ultimi 12 mesi per fornitore e prodotto (note di credito comprese)."""
    if not skus:
        return {}
    lines = purchase_lines_select(_PRIMARY_TENANT, skus=skus, date_from=today - timedelta(days=365)).subquery()
    rows = (await db.execute(select(lines.c.fornitore_id, lines.c.sku_interno, func.sum(lines.c.importo_netto))
                             .group_by(lines.c.fornitore_id, lines.c.sku_interno))).all()
    return {(fid, sku): Decimal(str(total or 0)) for fid, sku, total in rows}


@router.get("/public/{token}", summary="Listino aperto del fornitore")
async def get_open_price_list(token: str, db: AsyncSession = Depends(get_db)):
    link, supplier_name = await _active_link(db, token)
    today = today_rome()
    rows = await _active_supplier_rows(db, link.fornitore_id)
    formats = await _offer_formats(db, link.fornitore_id, rows)
    approved_names = await _approved_names(db, link.fornitore_id)
    skus = {row.sku_interno for row in rows}
    sector = {p.sku_interno: p for p in await sector_products(db, link.fornitore_id, skus, today)}
    spend = await _spend_by_sku(db, skus | set(sector), today)
    in_use = await skus_in_use(db, set(sector) - skus, today)
    sector = {sku: p for sku, p in sector.items() if sku in skus or sku in in_use or spend.get(sku, 0) > 0}
    best = await _best_prices(db, link.fornitore_id, skus)
    pending = await _pending_changes(db, link.fornitore_id)
    proposals = await _pending_proposals(db, link.fornitore_id)
    pending_names = {p.listino_id_origine: p.nome_fornitore for p in proposals if p.tipo == PROPOSTA_NOME}
    pending_units = {p.listino_id_origine: {
        "unita_vendita": p.unita_vendita, "contenuto_quantita": _money(p.contenuto_quantita),
        "contenuto_unita": p.contenuto_unita, "prezzo": _money(p.prezzo),
    } for p in proposals if p.tipo == PROPOSTA_UNITA}
    # Il nome in grassetto è il nostro (nome matriciale del catalogo), non la dicitura del fornitore.
    our_names = {sku: name for sku, name in (await db.execute(select(Product.sku_interno, Product.canonical_name).where(
        Product.sku_interno.in_(skus)))).all() if name} if skus else {}
    ranked = sorted(rows, key=lambda r: (-spend.get(r.sku_interno, Decimal(0)), r.descrizione.casefold()))
    # I più acquistati si contano sulla lista del settore: sono gli stessi per tutti i fornitori.
    top_skus = top_products(sector.keys() if sector else skus, spend)
    absent = set((await db.scalars(select(SupplierProductAbsence.sku_interno).where(
        SupplierProductAbsence.fornitore_id == link.fornitore_id))).all())
    pending_quotes = {p.sku_interno: p for p in proposals if p.tipo == PROPOSTA_PRODOTTO_NUOVO and p.sku_interno}
    names = {**{sku: p.canonical_name or "" for sku, p in sector.items()}, **our_names}
    order = {sku: i for i, sku in enumerate(sorted(skus | set(sector), key=lambda s: (
        -spend.get(s, Decimal(0)), (names.get(s) or s).casefold())))}
    missing = sorted((p for sku, p in sector.items() if sku not in skus), key=lambda p: order[p.sku_interno])
    quotes = [{
        "ordine": order[p.sku_interno],
        "sku_interno": p.sku_interno,
        "descrizione": p.canonical_name,
        "unita_confronto": p.comparison_unit,
        "importante": p.sku_interno in top_skus,
        "non_presente": p.sku_interno in absent,
        "in_attesa": {
            "nome": q.nome_fornitore, "unita_vendita": q.unita_vendita,
            "contenuto_quantita": _money(q.contenuto_quantita), "contenuto_unita": q.contenuto_unita,
            "prezzo": _money(q.prezzo),
        } if (q := pending_quotes.get(p.sku_interno)) else None,
    } for p in missing]
    items = []
    for row in ranked:
        quantity, unit, wording, brand = formats.get(row.id, (None, None, None, None))
        wording = approved_names.get(offer_key(row.sku_interno, row.supplier_product_alias_id)) or wording
        change = pending.get(offer_key(row.sku_interno, row.supplier_product_alias_id))
        items.append({
            "ordine": order[row.sku_interno],
            "listino_id": row.id,
            "descrizione": our_names.get(row.sku_interno) or row.descrizione,
            "dicitura": wording,
            "nome_in_attesa": pending_names.get(row.id),
            "unita_in_attesa": pending_units.get(row.id),
            "marca": brand,
            "formato": _format_label(quantity, unit or (row.unita_misura or "").upper() or None),
            "prezzo": _money(row.prezzo_pattuito),
            "importante": row.sku_interno in top_skus,
            # Solo "siete / non siete i più convenienti": mai il prezzo degli altri.
            "siete_i_piu_convenienti": best[row.sku_interno][2] if row.sku_interno in best else None,
            "in_attesa": {
                "tipo": change.tipo, "prezzo": _money(change.prezzo_nuovo),
                "decorrenza": change.decorrenza.isoformat(),
                "sospesa": change.stato == "trattenuto",
            } if change else None,
        })
    link.ultimo_accesso_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "fornitore": supplier_name,
        "oggi": today.isoformat(),
        "prossima_data_fissa": next_fixed_date(today).isoformat(),
        "ultima_conferma": link.ultima_conferma_at.isoformat() if link.ultima_conferma_at else None,
        "importanti": len(top_skus),
        "items": items,
        "da_quotare": quotes,
        "prodotti_proposti": [{
            "id": p.id, "nome": p.nome_fornitore, "unita_vendita": p.unita_vendita,
            "contenuto_quantita": _money(p.contenuto_quantita), "contenuto_unita": p.contenuto_unita,
            "prezzo": _money(p.prezzo), "created_at": p.created_at.isoformat(),
        } for p in proposals if p.tipo == PROPOSTA_PRODOTTO_NUOVO and not p.sku_interno],
    }


def top_products(skus, spend: dict[str, Decimal], limit: int = TOP_PRODUCTS) -> set[str]:
    """I prodotti su cui spendiamo di più (solo quelli con acquisti)."""
    ranked = sorted((s for s in set(skus) if spend.get(s, 0) > 0), key=lambda s: (-spend[s], s))
    return set(ranked[:limit])


class PriceUpdate(BaseModel):
    listino_id: int
    prezzo: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=4)
    non_trattato: bool = False
    nota: str | None = Field(default=None, max_length=500)
    # Il nome con cui il fornitore chiama il prodotto (il nostro nome non cambia).
    nome_fornitore: str | None = Field(default=None, max_length=255)
    # Nuova unità di vendita, con il prezzo in quella unità: va all'ufficio prima di valere.
    unita: "UnitChange | None" = None


class UnitChange(BaseModel):
    unita_vendita: str
    contenuto_quantita: Decimal | None = Field(default=None, gt=0, lt=Decimal("1000000"), decimal_places=4)
    contenuto_unita: str | None = None
    prezzo: Decimal = Field(gt=0, lt=Decimal("100000000"), decimal_places=4)


PriceUpdate.model_rebuild()


class NewProduct(BaseModel):
    nome: str = Field(min_length=2, max_length=255)
    unita_vendita: str
    contenuto_quantita: Decimal | None = Field(default=None, gt=0, lt=Decimal("1000000"), decimal_places=4)
    contenuto_unita: str | None = None
    prezzo: Decimal = Field(gt=0, lt=Decimal("100000000"), decimal_places=4)


class Quote(NewProduct):
    """Prezzo per un prodotto della lista di settore che il fornitore non aveva a listino.
    nome = come il fornitore lo chiama in fattura."""
    sku_interno: str = Field(min_length=1, max_length=100)


class PriceUpdates(BaseModel):
    modifiche: list[PriceUpdate] = Field(default_factory=list, max_length=2000)
    nuovi: list[NewProduct] = Field(default_factory=list, max_length=200)
    quotazioni: list[Quote] = Field(default_factory=list, max_length=2000)
    # Prodotti della lista segnati «non lo abbiamo», e quelli da cui si toglie il segno.
    assenti: list[str] = Field(default_factory=list, max_length=2000)
    presenti: list[str] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def at_least_one(self):
        if not (self.modifiche or self.nuovi or self.quotazioni or self.assenti or self.presenti):
            raise ValueError("Nessuna modifica da inviare")
        if set(self.assenti) & ({q.sku_interno for q in self.quotazioni} | set(self.presenti)):
            raise ValueError("Un prodotto è segnato sia «non lo abbiamo» sia con un prezzo")
        return self


def _clean_name(value: str | None) -> str:
    return " ".join((value or "").split())


def validate_new_product(product: NewProduct) -> NewProduct:
    """Controlla i 4 campi del prodotto nuovo: il contenuto serve solo per cartone e cassa."""
    nome = _clean_name(product.nome)
    if len(nome) < 2:
        raise HTTPException(status_code=422, detail="Prodotto nuovo: scrivete il nome")
    unit, quantity, content_unit = validate_sale_unit(product.unita_vendita, product.contenuto_quantita,
                                                      product.contenuto_unita, nome)
    return product.model_copy(update={"nome": nome, "unita_vendita": unit,
                                      "contenuto_quantita": quantity, "contenuto_unita": content_unit})


def validate_sale_unit(unita_vendita: str | None, contenuto_quantita: Decimal | None, contenuto_unita: str | None,
                       label: str) -> tuple[str, Decimal | None, str | None]:
    """Come si vende: al kg, al pezzo, al litro, oppure a cartone o cassa con quello che c'è dentro."""
    unit = (unita_vendita or "").strip().upper()
    if unit not in UNITA_VENDITA:
        raise HTTPException(status_code=422, detail=f"{label}: scegliete come lo vendete")
    if unit not in UNITA_CON_CONTENUTO:
        return unit, None, None
    content_unit = (contenuto_unita or "").strip().upper()
    if contenuto_quantita is None or content_unit not in UNITA_CONTENUTO:
        raise HTTPException(status_code=422, detail=f"{label}: indicate quanti pezzi o kg ci sono dentro")
    _check_quantity(contenuto_quantita, content_unit, label)
    return unit, contenuto_quantita, content_unit


async def _save_unit_proposal(db: AsyncSession, link: SupplierPriceLink, row: ListinoMaster, change: UnitChange,
                              label: str, now: datetime, ip: str | None) -> None:
    """Salva la nuova unità proposta per una riga; conta l'ultima inviata."""
    unit, quantity, content_unit = validate_sale_unit(change.unita_vendita, change.contenuto_quantita,
                                                      change.contenuto_unita, label)
    pending = (await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.fornitore_id == link.fornitore_id,
        SupplierProductProposal.tipo == PROPOSTA_UNITA,
        SupplierProductProposal.listino_id_origine == row.id,
        SupplierProductProposal.stato == PROPOSTA_IN_ATTESA,
    ).with_for_update())).scalars().all()
    for old in pending:
        old.stato = PROPOSTA_SOSTITUITA
        old.decisione_at = now
    proposal = SupplierProductProposal(
        link_id=link.id, fornitore_id=link.fornitore_id, tipo=PROPOSTA_UNITA, stato=PROPOSTA_IN_ATTESA,
        listino_id_origine=row.id, sku_interno=row.sku_interno,
        supplier_product_alias_id=row.supplier_product_alias_id, nome_fornitore=label[:255],
        unita_vendita=unit, contenuto_quantita=quantity, contenuto_unita=content_unit, prezzo=change.prezzo,
        created_at=now, ip=ip,
    )
    db.add(proposal)
    await db.flush()
    for old in pending:
        old.sostituita_da_id = proposal.id


async def _approved_names(db: AsyncSession, fornitore_id: int) -> dict[str, str]:
    """Ultimo nome approvato dall'ufficio per ogni offerta del fornitore (stesso prodotto e variante)."""
    rows = (await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.fornitore_id == fornitore_id,
        SupplierProductProposal.tipo == PROPOSTA_NOME,
        SupplierProductProposal.stato == PROPOSTA_APPROVATA,
    ).order_by(SupplierProductProposal.decisione_at, SupplierProductProposal.id))).scalars().all()
    return {offer_key(p.sku_interno, p.supplier_product_alias_id): p.nome_fornitore for p in rows if p.sku_interno}


async def _pending_proposals(db: AsyncSession, fornitore_id: int) -> list[SupplierProductProposal]:
    return list((await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.fornitore_id == fornitore_id,
        SupplierProductProposal.stato == PROPOSTA_IN_ATTESA,
    ).order_by(SupplierProductProposal.id))).scalars().all())


async def _save_name_proposal(db: AsyncSession, link: SupplierPriceLink, row: ListinoMaster, current: str | None,
                              name: str, now: datetime, ip: str | None) -> bool:
    """Salva il nome proposto per una riga; conta l'ultimo inviato. False se non cambia nulla."""
    pending = (await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.fornitore_id == link.fornitore_id,
        SupplierProductProposal.tipo == PROPOSTA_NOME,
        SupplierProductProposal.listino_id_origine == row.id,
        SupplierProductProposal.stato == PROPOSTA_IN_ATTESA,
    ).with_for_update())).scalar_one_or_none()
    same_as_current = normalize_text(name) == normalize_text(current or "")
    if pending and normalize_text(pending.nome_fornitore) == normalize_text(name):
        return False
    if pending:
        pending.stato = PROPOSTA_SOSTITUITA
        pending.decisione_at = now
        await db.flush()
    if same_as_current:
        return pending is not None  # riportato al nome di prima: la proposta in attesa è annullata
    proposal = SupplierProductProposal(
        link_id=link.id, fornitore_id=link.fornitore_id, tipo=PROPOSTA_NOME, stato=PROPOSTA_IN_ATTESA,
        listino_id_origine=row.id, sku_interno=row.sku_interno,
        supplier_product_alias_id=row.supplier_product_alias_id, nome_precedente=current,
        nome_fornitore=name, created_at=now, ip=ip,
    )
    db.add(proposal)
    await db.flush()
    if pending:
        pending.sostituita_da_id = proposal.id
    return True


async def _save_sector_answers(db: AsyncSession, link: SupplierPriceLink, payload: "PriceUpdates", own_skus: set[str],
                               today, now: datetime, ip: str | None, summary: dict) -> None:
    """Risposte sui prodotti della lista di settore che il fornitore non ha a listino.

    Un prezzo diventa una proposta già collegata al nostro prodotto: entra in listino
    quando l'ufficio dà il via libera. «Non lo abbiamo» resta segnato finché il
    fornitore non lo toglie o scrive un prezzo.
    """
    sector = {p.sku_interno: p for p in await sector_products(db, link.fornitore_id, own_skus, today)}
    asked = [q.sku_interno for q in payload.quotazioni] + payload.assenti + payload.presenti
    if len(set(q.sku_interno for q in payload.quotazioni)) != len(payload.quotazioni):
        raise HTTPException(status_code=422, detail="Lo stesso prodotto compare due volte")
    if any(sku not in sector for sku in asked):
        raise HTTPException(status_code=409, detail="Un prodotto non è più nella lista: ricarica la pagina")
    absences = {a.sku_interno: a for a in (await db.execute(select(SupplierProductAbsence).where(
        SupplierProductAbsence.fornitore_id == link.fornitore_id,
        SupplierProductAbsence.sku_interno.in_(asked),
    ).with_for_update())).scalars().all()} if asked else {}
    pending = {p.sku_interno: p for p in await _pending_proposals(db, link.fornitore_id)
               if p.tipo == PROPOSTA_PRODOTTO_NUOVO and p.sku_interno}
    for quote in payload.quotazioni:
        product = sector[quote.sku_interno]
        if quote.sku_interno in own_skus:
            raise HTTPException(status_code=409, detail=f"{product.canonical_name}: è già nel vostro listino, ricarica la pagina")
        checked = validate_new_product(quote)
        previous = pending.get(quote.sku_interno)
        if previous:
            previous.stato = PROPOSTA_SOSTITUITA
            previous.decisione_at = now
        proposal = SupplierProductProposal(
            link_id=link.id, fornitore_id=link.fornitore_id, tipo=PROPOSTA_PRODOTTO_NUOVO,
            stato=PROPOSTA_IN_ATTESA, sku_interno=quote.sku_interno, nome_fornitore=checked.nome,
            unita_vendita=checked.unita_vendita, contenuto_quantita=checked.contenuto_quantita,
            contenuto_unita=checked.contenuto_unita, prezzo=checked.prezzo, created_at=now, ip=ip,
        )
        db.add(proposal)
        await db.flush()
        if previous:
            previous.sostituita_da_id = proposal.id
        if quote.sku_interno in absences:
            await db.delete(absences.pop(quote.sku_interno))
        summary["quotati"] += 1
    for sku in payload.presenti:
        if sku in absences:
            await db.delete(absences.pop(sku))
            summary["di_nuovo_presenti"] += 1
    for sku in payload.assenti:
        if sku in own_skus:
            raise HTTPException(status_code=409, detail=(
                f"{sector[sku].canonical_name}: è nel vostro listino, usate «non lo tratto più»"))
        if sku not in absences:
            db.add(SupplierProductAbsence(fornitore_id=link.fornitore_id, sku_interno=sku, link_id=link.id, created_at=now))
            summary["non_presenti"] += 1
        previous = pending.get(sku)
        if previous:  # un prezzo mandato prima e non ancora approvato non vale più
            previous.stato = PROPOSTA_SOSTITUITA
            previous.decisione_at = now
    await db.flush()


@router.post("/public/{token}/submit", summary="Il fornitore invia i prezzi cambiati")
async def submit_open_price_list(token: str, payload: PriceUpdates, request: Request,
                                 db: AsyncSession = Depends(get_db)):
    link, _ = await _active_link(db, token, for_update=True)
    new_products = [validate_new_product(product) for product in payload.nuovi]
    ids = [update.listino_id for update in payload.modifiche]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Lo stesso prodotto compare due volte")
    rows = {row.id: row for row in await _active_supplier_rows(db, link.fornitore_id)}
    named_rows = [rows[u.listino_id] for u in payload.modifiche
                  if (u.nome_fornitore is not None or u.unita is not None) and u.listino_id in rows]
    wording: dict[int, str | None] = {}
    if named_rows:
        approved_names = await _approved_names(db, link.fornitore_id)
        named_formats = await _offer_formats(db, link.fornitore_id, named_rows)
        wording = {row.id: approved_names.get(offer_key(row.sku_interno, row.supplier_product_alias_id))
                   or named_formats.get(row.id, (None, None, None, None))[2] for row in named_rows}
    now = datetime.now(timezone.utc)
    today = today_rome()
    ip = (request.client.host if request.client else None)
    summary = {"ribassi": 0, "aumenti": 0, "non_trattati": 0, "sospese": 0, "annullate": 0, "invariati": 0,
               "nomi": 0, "nuovi": 0, "unita": 0, "quotati": 0, "non_presenti": 0, "di_nuovo_presenti": 0}
    for update in payload.modifiche:
        row = rows.get(update.listino_id)
        if row is None:
            raise HTTPException(status_code=409, detail="Un prodotto non è più nel vostro listino: ricarica la pagina")
        name = _clean_name(update.nome_fornitore) if update.nome_fornitore is not None else None
        has_price = update.non_trattato or update.prezzo is not None
        if update.non_trattato and update.prezzo is not None:
            raise HTTPException(status_code=422, detail=f"{row.descrizione}: indica un prezzo oppure «non lo tratto più»")
        if update.unita is not None and has_price:
            raise HTTPException(status_code=422, detail=(
                f"{row.descrizione}: se cambiate l'unità, scrivete il prezzo nella nuova unità e non nella casella del prezzo"))
        if not has_price and not name and update.unita is None:
            raise HTTPException(status_code=422,
                                detail=f"{row.descrizione}: indica un prezzo, «non lo tratto più», il vostro nome o l'unità")
        if update.unita is not None:
            await _save_unit_proposal(db, link, row, update.unita, wording.get(row.id) or row.descrizione, now, ip)
            summary["unita"] += 1
        if name is not None and len(name) < 2:
            raise HTTPException(status_code=422, detail=f"{row.descrizione}: il vostro nome è troppo corto")
        if name and await _save_name_proposal(db, link, row, wording.get(row.id), name, now, ip):
            summary["nomi"] += 1
        if not has_price:
            continue
        key = offer_key(row.sku_interno, row.supplier_product_alias_id)
        await db.execute(select(func.pg_advisory_xact_lock(offer_lock_key(link.fornitore_id, key))))
        pending = (await db.execute(select(SupplierPriceChange).where(
            SupplierPriceChange.fornitore_id == link.fornitore_id,
            SupplierPriceChange.chiave_offerta == key,
            SupplierPriceChange.stato.in_(STATI_IN_ATTESA),
        ).with_for_update())).scalar_one_or_none()
        old_price = Decimal(str(row.prezzo_pattuito))
        decision = decide_change(today=today, prezzo_vecchio=old_price, prezzo_nuovo=update.prezzo,
                                 non_trattato=update.non_trattato)
        if pending and pending.tipo == decision.tipo and pending.prezzo_nuovo == update.prezzo:
            continue  # stessa modifica già in attesa
        if pending:
            # Conta l'ultimo caricamento: la modifica in attesa è superata.
            pending.stato = STATO_SOSTITUITO
            pending.decisione_at = now
            await db.flush()
        if decision.stato is None:
            summary["annullate" if pending else "invariati"] += 1
            continue
        change = SupplierPriceChange(
            link_id=link.id, fornitore_id=link.fornitore_id, sku_interno=row.sku_interno,
            supplier_product_alias_id=row.supplier_product_alias_id, chiave_offerta=key,
            listino_id_origine=row.id, prezzo_vecchio=old_price, prezzo_nuovo=update.prezzo,
            unita_misura=row.unita_misura, tipo=decision.tipo, stato=decision.stato,
            decorrenza=decision.decorrenza, motivo_trattenuta=decision.motivo_trattenuta,
            nota_fornitore=(update.nota or "").strip() or None, created_at=now, ip=ip,
        )
        db.add(change)
        await db.flush()
        if pending:
            pending.sostituito_da_id = change.id
        if decision.stato == STATO_PROGRAMMATO and decision.decorrenza <= today:
            # Un ribasso vale da subito: entra ora nel listino, così gli ordini lo usano dal minuto dopo
            # (senza aspettare il giro automatico del giorno).
            await apply_change_now(db, change.id, today=today, now=now)
        if decision.motivo_trattenuta:
            summary["sospese"] += 1
        summary[{"ribasso": "ribassi", "aumento": "aumenti", "non_trattato": "non_trattati"}[decision.tipo]] += 1
    if new_products:
        pending_new = {normalize_text(p.nome_fornitore): p for p in await _pending_proposals(db, link.fornitore_id)
                       if p.tipo == PROPOSTA_PRODOTTO_NUOVO}
        for product in new_products:
            # Stesso prodotto già proposto e in attesa: conta l'ultimo invio.
            previous = pending_new.get(normalize_text(product.nome))
            if previous:
                previous.stato = PROPOSTA_SOSTITUITA
                previous.decisione_at = now
            proposal = SupplierProductProposal(
                link_id=link.id, fornitore_id=link.fornitore_id, tipo=PROPOSTA_PRODOTTO_NUOVO,
                stato=PROPOSTA_IN_ATTESA, nome_fornitore=product.nome, unita_vendita=product.unita_vendita,
                contenuto_quantita=product.contenuto_quantita, contenuto_unita=product.contenuto_unita,
                prezzo=product.prezzo, created_at=now, ip=ip,
            )
            db.add(proposal)
            await db.flush()
            if previous:
                previous.sostituita_da_id = proposal.id
            pending_new[normalize_text(product.nome)] = proposal
            summary["nuovi"] += 1
    if payload.quotazioni or payload.assenti or payload.presenti:
        await _save_sector_answers(db, link, payload, {r.sku_interno for r in rows.values()}, today, now, ip, summary)
    link.ultima_conferma_at = now
    await db.commit()
    return {"status": "ok", "riepilogo": summary, "prossima_data_fissa": next_fixed_date(today).isoformat()}


@router.post("/public/{token}/confirm-unchanged", summary="Il fornitore conferma tutto il listino invariato")
async def confirm_unchanged(token: str, db: AsyncSession = Depends(get_db)):
    link, _ = await _active_link(db, token, for_update=True)
    link.ultima_conferma_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok"}


# --- Ufficio acquisti: crea, rileggi e disattiva il link -------------------------------------


def _link_view(link: SupplierPriceLink | None) -> dict | None:
    if link is None:
        return None
    token = _link_token(link)
    return {
        "id": link.id,
        "attivo": link.attivo,
        "path": f"/fornitore/prezzi/{token}" if token else None,
        "created_at": link.created_at.isoformat(),
        "ultimo_accesso_at": link.ultimo_accesso_at.isoformat() if link.ultimo_accesso_at else None,
        "ultima_conferma_at": link.ultima_conferma_at.isoformat() if link.ultima_conferma_at else None,
    }


async def _current_link(db: AsyncSession, fornitore_id: int) -> SupplierPriceLink | None:
    return (await db.execute(select(SupplierPriceLink).options(noload("*")).where(
        SupplierPriceLink.fornitore_id == fornitore_id, SupplierPriceLink.attivo.is_(True),
    ).with_for_update())).scalar_one_or_none()


@router.get("/supplier/{fornitore_id}", summary="Link fisso attivo del fornitore")
async def get_supplier_link(fornitore_id: int, admin: Utente = Depends(require_admin),
                            db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    link = (await db.execute(select(SupplierPriceLink).options(noload("*")).where(
        SupplierPriceLink.fornitore_id == fornitore_id, SupplierPriceLink.attivo.is_(True),
    ))).scalar_one_or_none()
    return {"link": _link_view(link)}


@router.post("/supplier/{fornitore_id}", summary="Crea il link fisso (o lo rinnova, disattivando il vecchio)")
async def create_supplier_link(fornitore_id: int, admin: Utente = Depends(require_admin),
                               db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    supplier = await db.get(Fornitore, fornitore_id, options=[noload("*")])
    if not supplier or supplier.archived_at or not supplier.attivo_whitelist:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o non attivo")
    await db.execute(select(func.pg_advisory_xact_lock(offer_lock_key(fornitore_id, "link"))))
    now = datetime.now(timezone.utc)
    old = await _current_link(db, fornitore_id)
    if old:
        old.attivo = False
        old.revocato_at = now
        await db.flush()
    token = secrets.token_urlsafe(32)
    link = SupplierPriceLink(fornitore_id=fornitore_id, token_hash=_hash(token), token_encrypted=_encrypt_token(token),
                             attivo=True, created_by_id=admin.id, created_at=now)
    db.add(link)
    await db.commit()
    return {"link": _link_view(link)}


async def _forecasts_for(db: AsyncSession, changes: list[SupplierPriceChange]) -> dict[tuple, Forecast]:
    """Prezzi di tutti i fornitori nel giorno in cui ciascun aumento entra, per quella voce."""
    by_day: dict = {}
    for change in changes:
        by_day.setdefault(change.decorrenza, set()).add(change.sku_interno)
    result: dict[tuple, Forecast] = {}
    for day, skus in by_day.items():
        for sku, forecast in (await forecast_on(db, skus, day)).items():
            result[(day, sku)] = forecast
    return result


def after_increase(forecast: Forecast | None, change: SupplierPriceChange, spesa_annua: Decimal | None,
                   suppliers: dict) -> dict | None:
    """Dopo l'aumento: resta il più conveniente? Se no, chi conviene e quanto si risparmia in un anno."""
    if forecast is None or not forecast.prezzi:
        return None
    best = forecast.migliore
    own = forecast.prezzi.get(change.fornitore_id)
    supplier = suppliers.get(best)
    result = {
        "resta_il_migliore": best == change.fornitore_id,
        "migliore_fornitore_id": best,
        "migliore_fornitore": supplier.nome_azienda if supplier else f"Fornitore {best}",
        "migliore_prezzo": _money(forecast.prezzi[best]),
        "prezzo_fornitore": _money(own),
        "unita_confronto": forecast.unita_confronto,
        "risparmio_annuo": None,
    }
    if own and own > 0 and best != change.fornitore_id and spesa_annua and spesa_annua > 0:
        result["risparmio_annuo"] = _money((spesa_annua * (own - forecast.prezzi[best]) / own).quantize(Decimal("0.01")))
    return result


@router.get("/overview/count",summary="Contatore del menu: sospese e aumenti in arrivo")
async def price_changes_count(admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    count = (await db.execute(select(func.count()).select_from(SupplierPriceChange).where(or_(
        SupplierPriceChange.stato == STATO_TRATTENUTO,
        and_(SupplierPriceChange.stato == STATO_PROGRAMMATO, SupplierPriceChange.tipo == TIPO_AUMENTO),
    )))).scalar_one()
    count += (await db.execute(select(func.count()).select_from(SupplierProductProposal).where(
        SupplierProductProposal.stato == PROPOSTA_IN_ATTESA))).scalar_one()
    return {"pending_count": count}


@router.get("/overview", summary="Variazioni listini: sospese, aumenti in arrivo, ribassi, solleciti")
async def price_changes_overview(admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    today = today_rome()
    now = datetime.now(timezone.utc)
    pending = (await db.execute(select(SupplierPriceChange).where(or_(
        SupplierPriceChange.stato == STATO_TRATTENUTO,
        and_(SupplierPriceChange.stato == STATO_PROGRAMMATO, SupplierPriceChange.tipo == TIPO_AUMENTO),
        and_(SupplierPriceChange.tipo == TIPO_RIBASSO,
             SupplierPriceChange.stato.in_((STATO_PROGRAMMATO, STATO_APPLICATO)),
             SupplierPriceChange.created_at >= now - timedelta(days=RIBASSI_GIORNI)),
    )))).scalars().all()
    links = (await db.execute(select(SupplierPriceLink).options(noload("*")).where(
        SupplierPriceLink.attivo.is_(True)))).scalars().all()
    proposals = (await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.stato == PROPOSTA_IN_ATTESA).order_by(SupplierProductProposal.id))).scalars().all()
    form_ends = await expired_form_suppliers(db, today)
    supplier_ids = ({c.fornitore_id for c in pending} | {link.fornitore_id for link in links}
                    | {p.fornitore_id for p in proposals} | set(form_ends))
    suppliers = {s.id: s for s in (await db.execute(select(Fornitore).options(noload("*")).where(
        Fornitore.id.in_(supplier_ids)))).scalars().all()} if supplier_ids else {}
    origin_ids = {c.listino_id_origine for c in pending if c.listino_id_origine}
    names = dict((await db.execute(select(ListinoMaster.id, ListinoMaster.descrizione).where(
        ListinoMaster.id.in_(origin_ids)))).all()) if origin_ids else {}
    spend = await _spend_by_supplier_sku(db, {c.sku_interno for c in pending}, today)

    def view(change: SupplierPriceChange) -> dict:
        supplier = suppliers.get(change.fornitore_id)
        return {
            "id": change.id, "fornitore_id": change.fornitore_id,
            "fornitore": supplier.nome_azienda if supplier else f"Fornitore {change.fornitore_id}",
            "prodotto": names.get(change.listino_id_origine) or change.sku_interno,
            "tipo": change.tipo, "prezzo_vecchio": _money(change.prezzo_vecchio),
            "prezzo_nuovo": _money(change.prezzo_nuovo), "unita": change.unita_misura,
            "decorrenza": change.decorrenza.isoformat(), "motivo": change.motivo_trattenuta,
            "nota": change.nota_fornitore,
            "impatto_annuo": _money(annual_impact(spend.get((change.fornitore_id, change.sku_interno)),
                                                  change.prezzo_vecchio, change.prezzo_nuovo)),
        }

    held = sorted((view(c) for c in pending if c.stato == STATO_TRATTENUTO), key=lambda v: v["decorrenza"])
    increase_changes = [c for c in pending if c.stato == STATO_PROGRAMMATO and c.tipo == TIPO_AUMENTO]
    forecasts = await _forecasts_for(db, increase_changes)
    best_ids = {f.migliore for f in forecasts.values() if f.migliore and f.migliore not in suppliers}
    if best_ids:
        suppliers.update({s.id: s for s in (await db.execute(select(Fornitore).options(noload("*")).where(
            Fornitore.id.in_(best_ids)))).scalars().all()})

    def increase_view(change: SupplierPriceChange) -> dict:
        result = view(change)
        result["dopo"] = after_increase(forecasts.get((change.decorrenza, change.sku_interno)), change,
                                        spend.get((change.fornitore_id, change.sku_interno)), suppliers)
        return result

    # In cima gli aumenti dopo i quali conviene un altro fornitore, poi quelli che costano di più.
    increases = sorted((increase_view(c) for c in increase_changes),
                       key=lambda v: (not (v["dopo"] and not v["dopo"]["resta_il_migliore"]),
                                      -Decimal(v["impatto_annuo"] or 0)))
    decreases = [view(c) for c in pending if c.tipo == TIPO_RIBASSO and c.stato != STATO_TRATTENUTO]
    saving = sum((-Decimal(v["impatto_annuo"]) for v in decreases if v["impatto_annuo"]), Decimal(0))

    proposal_skus = {p.sku_interno for p in proposals if p.sku_interno}
    our_names = dict((await db.execute(select(Product.sku_interno, Product.canonical_name).where(
        Product.sku_interno.in_(proposal_skus)))).all()) if proposal_skus else {}
    unit_rows = {p.listino_id_origine for p in proposals if p.tipo == PROPOSTA_UNITA and p.listino_id_origine}
    current_prices = {row.id: row for row in (await db.execute(select(ListinoMaster).options(noload("*")).where(
        ListinoMaster.id.in_(unit_rows)))).scalars().all()} if unit_rows else {}
    # Il formato attuale come lo vede il fornitore (es. «cassa 5 KG»), non l'unità interna «conf».
    current_formats: dict[int, str] = {}
    for supplier_id in {row.fornitore_id for row in current_prices.values()}:
        supplier_rows = [row for row in current_prices.values() if row.fornitore_id == supplier_id]
        for row_id, (quantity, unit, _w, _b) in (await _offer_formats(db, supplier_id, supplier_rows)).items():
            current_formats[row_id] = _format_label(quantity, unit or (current_prices[row_id].unita_misura or "").upper() or None)
    proposal_views = [{
        "prezzo_attuale": _money(current_prices[p.listino_id_origine].prezzo_pattuito)
        if p.listino_id_origine in current_prices else None,
        "formato_attuale": current_formats.get(p.listino_id_origine),
        "id": p.id, "tipo": p.tipo, "fornitore_id": p.fornitore_id,
        "fornitore": suppliers[p.fornitore_id].nome_azienda if p.fornitore_id in suppliers else f"Fornitore {p.fornitore_id}",
        "nostro_nome": our_names.get(p.sku_interno) if p.sku_interno else None,
        "sku_interno": p.sku_interno,
        "nome_precedente": p.nome_precedente, "nome_fornitore": p.nome_fornitore,
        "unita_vendita": p.unita_vendita, "contenuto_quantita": _money(p.contenuto_quantita),
        "contenuto_unita": p.contenuto_unita, "prezzo": _money(p.prezzo), "created_at": p.created_at.isoformat(),
    } for p in proposals]

    deadline = reminder_deadline(today)
    since = previous_fixed_date(today)
    stale_before = now - timedelta(days=NON_CONFERMATO_GIORNI)
    reminders, stale = [], []
    for link in links:
        supplier = suppliers.get(link.fornitore_id)
        if not supplier or supplier.archived_at or not supplier.attivo_whitelist:
            continue
        token = _link_token(link)
        row = {
            "fornitore_id": supplier.id, "fornitore": supplier.nome_azienda,
            "telefono": supplier.telefono_contatto, "path": f"/fornitore/prezzi/{token}" if token else None,
            "ultima_conferma_at": link.ultima_conferma_at.isoformat() if link.ultima_conferma_at else None,
        }
        last = link.ultima_conferma_at
        if deadline and (last is None or last.astimezone(ROME).date() < since):
            reminders.append(row)
        if (last or link.created_at) < stale_before:
            stale.append(row)
    reminders.sort(key=lambda r: r["fornitore"].casefold())
    stale.sort(key=lambda r: r["ultima_conferma_at"] or "")
    link_paths = {link.fornitore_id: _link_token(link) for link in links}
    renewals = sorted((
        {"fornitore_id": sid, "fornitore": suppliers[sid].nome_azienda, "telefono": suppliers[sid].telefono_contatto,
         "path": f"/fornitore/prezzi/{link_paths[sid]}" if link_paths.get(sid) else None, "fino_al": end.isoformat()}
        for sid, end in form_ends.items()
        if sid in suppliers and not suppliers[sid].archived_at and suppliers[sid].attivo_whitelist
    ), key=lambda r: (r["fino_al"], r["fornitore"].casefold()))
    return {
        "oggi": today.isoformat(),
        "prossima_data_fissa": next_fixed_date(today).isoformat(),
        "contatore": len(held) + len(increases) + len(proposal_views),
        "proposte": proposal_views,
        "sospese": held,
        "aumenti": increases,
        "ribassi": {"numero": len(decreases), "risparmio_annuo": _money(saving), "giorni": RIBASSI_GIORNI},
        "solleciti": {"scadenza": deadline.isoformat() if deadline else None, "fornitori": reminders},
        "non_confermati": {"giorni": NON_CONFERMATO_GIORNI, "fornitori": stale},
        "listini_da_rinnovare": renewals,
    }


async def expired_form_suppliers(db: AsyncSession, today) -> dict[int, "date"]:
    """Fornitori il cui ultimo modulo prezzi indicava «valido fino al» una data già passata.

    I prezzi non scadono: restano quelli a sistema finché il fornitore non manda il
    listino nuovo. Qui si raccoglie solo chi va sollecitato. Non compare chi ha già
    una risposta in attesa di approvazione o un modulo approvato ancora valido.
    """
    requests = (await db.execute(select(
        SupplierPriceFormRequest.supplier_id, SupplierPriceFormRequest.status,
        SupplierPriceFormRequest.validita_inviata_a,
    ).where(SupplierPriceFormRequest.status.in_(("approved", "submitted"))))).all()
    ends: dict[int, date] = {}
    still_valid: set[int] = set()
    for supplier_id, status, valid_to in requests:
        if status == "submitted" or valid_to is None or valid_to >= today:
            still_valid.add(supplier_id)
        elif valid_to > ends.get(supplier_id, date.min):
            ends[supplier_id] = valid_to
    return {sid: end for sid, end in ends.items() if sid not in still_valid}


@router.post("/supplier/{fornitore_id}/revoke", summary="Disattiva il link fisso del fornitore")
async def revoke_supplier_link(fornitore_id: int, admin: Utente = Depends(require_admin),
                               db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    link = await _current_link(db, fornitore_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Nessun link attivo")
    link.attivo = False
    link.revocato_at = datetime.now(timezone.utc)
    await db.commit()
    return {"link": None}


@router.get("/suppliers", summary="Fornitori attivi con il loro link fisso")
async def list_supplier_links(admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    suppliers = (await db.execute(select(Fornitore).options(noload("*")).where(
        Fornitore.archived_at.is_(None), Fornitore.attivo_whitelist.is_(True),
    ).order_by(Fornitore.nome_azienda))).scalars().all()
    links = {link.fornitore_id: link for link in (await db.execute(select(SupplierPriceLink).options(noload("*"))
                                                                   .where(SupplierPriceLink.attivo.is_(True)))).scalars().all()}
    return {"fornitori": [{"fornitore_id": s.id, "fornitore": s.nome_azienda, "telefono": s.telefono_contatto,
                           "link": _link_view(links.get(s.id))} for s in suppliers]}


# --- Ufficio acquisti: via libera, rifiuto, altro prezzo ---------------------------------------

# Cosa si può fare su una modifica, secondo il suo stato.
AZIONI_PERMESSE = {
    "approva": (STATO_TRATTENUTO,),
    "rifiuta": (STATO_TRATTENUTO, STATO_PROGRAMMATO),
    "altro_prezzo": (STATO_TRATTENUTO, STATO_PROGRAMMATO),
}


class ForcedPrice(BaseModel):
    prezzo: Decimal = Field(gt=0, lt=Decimal("100000000"), decimal_places=4)


async def _change_for_decision(db: AsyncSession, change_id: int, action: str) -> SupplierPriceChange:
    change = await db.get(SupplierPriceChange, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Modifica non trovata")
    # Stesso ordine della pagina del fornitore e del job: prima il lock dell'offerta, poi la riga.
    await db.execute(select(func.pg_advisory_xact_lock(offer_lock_key(change.fornitore_id, change.chiave_offerta))))
    await db.refresh(change, with_for_update=True)
    if change.stato not in AZIONI_PERMESSE[action]:
        raise HTTPException(status_code=409, detail="La modifica è già stata decisa o superata: ricarica la pagina")
    return change


@router.post("/changes/{change_id}/approve", summary="Via libera a una modifica sospesa")
async def approve_change(change_id: int, admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    change = await _change_for_decision(db, change_id, "approva")
    change.stato = STATO_PROGRAMMATO
    change.decisione_by_id = admin.id
    change.decisione_at = datetime.now(timezone.utc)
    await db.flush()
    # Un ribasso vale da subito: si applica ora, senza aspettare il giro di domani.
    applied = await apply_change_now(db, change.id)
    await db.commit()
    return {"status": "ok", "stato": change.stato, "decorrenza": change.decorrenza.isoformat(), "esito": applied}


@router.post("/changes/{change_id}/reject", summary="Rifiuta una modifica sospesa o un aumento in arrivo")
async def reject_change(change_id: int, admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    change = await _change_for_decision(db, change_id, "rifiuta")
    change.stato = STATO_RIFIUTATO
    change.decisione_by_id = admin.id
    change.decisione_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok", "stato": change.stato}


@router.post("/changes/{change_id}/force", summary="L'ufficio decide un altro prezzo al posto di quello inviato")
async def force_change_price(change_id: int, payload: ForcedPrice, admin: Utente = Depends(require_admin),
                             db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    change = await _change_for_decision(db, change_id, "altro_prezzo")
    now = datetime.now(timezone.utc)
    change.decisione_by_id = admin.id
    change.decisione_at = now
    if change.prezzo_vecchio is not None and payload.prezzo == change.prezzo_vecchio:
        # Stesso prezzo di prima: equivale a non accettare la modifica.
        change.stato = STATO_RIFIUTATO
        await db.commit()
        return {"status": "ok", "stato": change.stato}
    decision = decide_change(today=today_rome(), prezzo_vecchio=change.prezzo_vecchio, prezzo_nuovo=payload.prezzo)
    change.stato = STATO_SOSTITUITO
    await db.flush()
    forced = SupplierPriceChange(
        link_id=change.link_id, fornitore_id=change.fornitore_id, sku_interno=change.sku_interno,
        supplier_product_alias_id=change.supplier_product_alias_id, chiave_offerta=change.chiave_offerta,
        listino_id_origine=change.listino_id_origine, prezzo_vecchio=change.prezzo_vecchio,
        prezzo_nuovo=payload.prezzo, unita_misura=change.unita_misura, tipo=decision.tipo,
        # Deciso dall'ufficio: non resta sospeso. Un aumento vale comunque dalla prossima data fissa.
        stato=STATO_PROGRAMMATO, decorrenza=decision.decorrenza, created_at=now,
        decisione_by_id=admin.id, decisione_at=now,
    )
    db.add(forced)
    await db.flush()
    change.sostituito_da_id = forced.id
    applied = await apply_change_now(db, forced.id)
    await db.commit()
    return {"status": "ok", "stato": forced.stato, "tipo": forced.tipo,
            "decorrenza": forced.decorrenza.isoformat(), "esito": applied}


# --- Ufficio acquisti: nomi e prodotti proposti dai fornitori -----------------------------------


def new_product_offer(proposal: SupplierProductProposal) -> tuple[Decimal, str]:
    """Confezione dell'offerta: al kg, al pezzo o al litro vale 1; a cartone o cassa conta il contenuto."""
    if proposal.unita_vendita in UNITA_CON_CONTENUTO:
        return Decimal(str(proposal.contenuto_quantita)), proposal.contenuto_unita
    return Decimal("1"), proposal.unita_vendita


async def _proposal_for_decision(db: AsyncSession, proposal_id: int, tipo: str | None = None) -> SupplierProductProposal:
    proposal = (await db.execute(select(SupplierProductProposal).where(
        SupplierProductProposal.id == proposal_id).with_for_update())).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposta non trovata")
    if proposal.stato != PROPOSTA_IN_ATTESA or (tipo and proposal.tipo != tipo):
        raise HTTPException(status_code=409, detail="La proposta è già stata decisa o superata: ricarica la pagina")
    return proposal


def _decide(proposal: SupplierProductProposal, admin: Utente, stato: str) -> None:
    proposal.stato = stato
    proposal.decisione_by_id = admin.id
    proposal.decisione_at = datetime.now(timezone.utc)


@router.get("/proposals/catalog-search", summary="Cerca nel catalogo il prodotto a cui collegare una proposta")
async def search_catalog_for_proposal(q: str = Query(min_length=2, max_length=100),
                                      admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    pattern = f"%{q.strip()}%"
    products = (await db.execute(select(Product).options(noload("*")).where(
        Product.is_active.is_(True), Product.sku_interno.is_not(None),
        or_(Product.canonical_name.ilike(pattern), Product.sku_interno.ilike(pattern)),
    ).order_by(Product.canonical_name).limit(20))).scalars().all()
    return {"prodotti": [{"sku_interno": p.sku_interno, "nome": p.canonical_name, "categoria": p.category,
                          "unita": p.comparison_unit} for p in products]}


@router.post("/proposals/{proposal_id}/approve-name", summary="Via libera al nome del fornitore per un prodotto")
async def approve_name_proposal(proposal_id: int, admin: Utente = Depends(require_admin),
                                db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    proposal = await _proposal_for_decision(db, proposal_id, PROPOSTA_NOME)
    product = await db.scalar(select(Product).options(noload("*")).where(Product.sku_interno == proposal.sku_interno))
    if product is None:
        raise HTTPException(status_code=409, detail="Il prodotto non è più nel catalogo")
    normalized = normalize_text(proposal.nome_fornitore)
    same_name = (await db.execute(select(SupplierProductAlias).options(noload("*")).where(
        SupplierProductAlias.supplier_id == proposal.fornitore_id,
        SupplierProductAlias.normalized_description == normalized,
        SupplierProductAlias.status == "approved",
    ))).scalars().all()
    clash = next((a for a in same_name if a.product_id != product.id), None)
    if clash:
        other = await db.get(Product, clash.product_id, options=[noload("*")])
        raise HTTPException(status_code=409, detail=(
            f"Questo nome è già collegato a un altro prodotto ({other.canonical_name if other else clash.product_id}): "
            "rifiuta la proposta oppure sistema prima il collegamento"))
    alias = next((a for a in same_name if a.product_id == product.id), None)
    if alias is None:
        # Si aggiunge il nome nuovo senza togliere il vecchio: le fatture si collegano con entrambi.
        base = await db.get(SupplierProductAlias, proposal.supplier_product_alias_id, options=[noload("*")]) \
            if proposal.supplier_product_alias_id else None
        now = datetime.now(timezone.utc)
        alias = SupplierProductAlias(
            supplier_id=proposal.fornitore_id, product_id=product.id, supplier_code=None,
            raw_description=proposal.nome_fornitore, normalized_description=normalized,
            brand=getattr(base, "brand", None), pack_qty=getattr(base, "pack_qty", None),
            fattore_confezione=getattr(base, "fattore_confezione", None),
            volume_ml=getattr(base, "volume_ml", None), weight_g=getattr(base, "weight_g", None),
            container_type=getattr(base, "container_type", None),
            status="approved", confidence_score=Decimal("1.00"), source="listino_aperto",
            first_seen_at=now, last_seen_at=now, created_at=now, updated_at=now,
        )
        db.add(alias)
        await db.flush()
    _decide(proposal, admin, PROPOSTA_APPROVATA)
    proposal.applicato_alias_id = alias.id
    await db.commit()
    return {"status": "ok", "stato": proposal.stato}


class ProposalProduct(BaseModel):
    sku_interno: str = Field(min_length=1, max_length=100)


@router.post("/proposals/{proposal_id}/approve-product",
             summary="Via libera a un prodotto nuovo: collegato al catalogo ed entra in listino da oggi")
async def approve_product_proposal(proposal_id: int, payload: ProposalProduct, admin: Utente = Depends(require_admin),
                                   db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    proposal = await _proposal_for_decision(db, proposal_id, PROPOSTA_PRODOTTO_NUOVO)
    product = await db.scalar(select(Product).options(noload("*")).where(
        Product.sku_interno == payload.sku_interno, Product.is_active.is_(True)))
    if product is None:
        raise HTTPException(status_code=404, detail="Prodotto del catalogo non trovato")
    quantity, unit = new_product_offer(proposal)
    offer_id = f"LA-{proposal.id}"
    # Stessa strada dei moduli prezzi: collegamento con la confezione e riga di listino.
    preview = await build_variant_preview(db, VariantPricePreviewRequest(rows=[VariantPriceRow(
        product_id=product.id, supplier_id=proposal.fornitore_id, sku=product.sku_interno, offer_id=offer_id,
        description=proposal.nome_fornitore, quantity=quantity, unit=unit,
        price=Decimal(str(proposal.prezzo)), package_confirmed=True,
    )], effective_date=today_rome()), admin.id)
    errors = preview.preview_payload.get("errors") or []
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(error["message"] for error in errors))
    result = await commit_variant_preview(db, preview, origine=ORIGINE_LISTINO_APERTO)
    alias_id = await db.scalar(select(SupplierProductAlias.id).where(
        SupplierProductAlias.supplier_id == proposal.fornitore_id, SupplierProductAlias.supplier_code == offer_id))
    _decide(proposal, admin, PROPOSTA_APPROVATA)
    proposal.sku_interno = product.sku_interno
    proposal.applicato_alias_id = alias_id
    proposal.applicato_listino_id = (result.get("listino_ids") or [None])[0]
    await db.commit()
    return {"status": "ok", "stato": proposal.stato, "listino_id": proposal.applicato_listino_id}


MOTIVO_UNITA_CAMBIATA = "unita_cambiata"


@router.post("/proposals/{proposal_id}/approve-unit",
             summary="Via libera alla nuova unità di vendita: il vecchio prezzo si chiude, il nuovo vale da oggi")
async def approve_unit_proposal(proposal_id: int, admin: Utente = Depends(require_admin),
                                db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    proposal = await _proposal_for_decision(db, proposal_id, PROPOSTA_UNITA)
    row = await db.get(ListinoMaster, proposal.listino_id_origine, options=[noload("*")]) \
        if proposal.listino_id_origine else None
    if row is None or row.fornitore_id != proposal.fornitore_id:
        raise HTTPException(status_code=409, detail="La riga di listino non c'è più: rifiuta la proposta")
    today = today_rome()
    if (row.data_scadenza is not None and row.data_scadenza < today) or await _newer_row_exists(db, row):
        raise HTTPException(status_code=409, detail=(
            "Il prezzo di partenza è già cambiato o scaduto: rifiuta e chiedi al fornitore di reinviare l'unità"))
    if row.data_inizio_validita >= today:
        raise HTTPException(status_code=409, detail="Il prezzo attuale è partito oggi: dai il via libera da domani")
    key = offer_key(row.sku_interno, row.supplier_product_alias_id)
    await db.execute(select(func.pg_advisory_xact_lock(offer_lock_key(proposal.fornitore_id, key))))
    product = await db.scalar(select(Product).options(noload("*")).where(
        Product.sku_interno == row.sku_interno, Product.is_active.is_(True)))
    if product is None:
        raise HTTPException(status_code=409, detail="Il prodotto non è più nel catalogo")
    base = await db.get(SupplierProductAlias, row.supplier_product_alias_id, options=[noload("*")]) \
        if row.supplier_product_alias_id else None
    # Stessa offerta se viene dai moduli prezzi (il collegamento prende la nuova confezione), altrimenti una nuova.
    reuse = base is not None and base.source == "normalized_sheet_offer" and bool(base.supplier_code)
    offer_id = base.supplier_code if reuse else f"LA-U-{proposal.id}"
    quantity, unit = new_product_offer(proposal)
    preview = await build_variant_preview(db, VariantPricePreviewRequest(rows=[VariantPriceRow(
        product_id=product.id, supplier_id=proposal.fornitore_id, sku=product.sku_interno, offer_id=offer_id,
        description=(base.raw_description if base and base.raw_description else row.descrizione)[:255],
        brand=getattr(base, "brand", None), quantity=quantity, unit=unit,
        price=Decimal(str(proposal.prezzo)), package_confirmed=True,
    )], effective_date=today), admin.id)
    errors = preview.preview_payload.get("errors") or []
    if errors:
        raise HTTPException(status_code=409, detail="; ".join(error["message"] for error in errors))
    result = await commit_variant_preview(db, preview, origine=ORIGINE_LISTINO_APERTO)
    new_ids = result.get("listino_ids") or []
    if row.data_scadenza is not None and new_ids:
        # Un prezzo a scadenza (es. frutta settimanale) resta a scadenza anche con la nuova unità.
        for new_row in (await db.execute(select(ListinoMaster).where(ListinoMaster.id.in_(new_ids)))).scalars():
            new_row.data_scadenza = row.data_scadenza
    # Il vecchio prezzo si chiude a ieri dentro commit_variant_preview: stessa offerta (riga sostituita)
    # oppure riga generica dello stesso prodotto (tagliata alla nuova decorrenza).
    now = datetime.now(timezone.utc)
    # Le modifiche di prezzo in attesa sulla vecchia unità non hanno più senso.
    for change in (await db.execute(select(SupplierPriceChange).where(
        SupplierPriceChange.fornitore_id == proposal.fornitore_id,
        SupplierPriceChange.chiave_offerta == key,
        SupplierPriceChange.stato.in_(STATI_IN_ATTESA),
    ).with_for_update())).scalars():
        change.stato = STATO_SOSTITUITO
        change.motivo_trattenuta = MOTIVO_UNITA_CAMBIATA
        change.decisione_at = now
    _decide(proposal, admin, PROPOSTA_APPROVATA)
    proposal.applicato_listino_id = new_ids[0] if new_ids else None
    proposal.applicato_alias_id = await db.scalar(select(SupplierProductAlias.id).where(
        SupplierProductAlias.supplier_id == proposal.fornitore_id, SupplierProductAlias.supplier_code == offer_id))
    await db.commit()
    return {"status": "ok", "stato": proposal.stato, "listino_id": proposal.applicato_listino_id}


@router.post("/proposals/{proposal_id}/reject", summary="Rifiuta un nome o un prodotto proposto dal fornitore")
async def reject_proposal(proposal_id: int, admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    proposal = await _proposal_for_decision(db, proposal_id)
    _decide(proposal, admin, PROPOSTA_RIFIUTATA)
    await db.commit()
    return {"status": "ok", "stato": proposal.stato}
