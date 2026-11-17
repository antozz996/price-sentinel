"""Listino sempre aperto: link fisso con cui il fornitore aggiorna i prezzi.

Il fornitore vede i suoi prezzi validi oggi (i 50 su cui spendiamo di piÃ¹ in alto)
e cambia solo il prezzo: dicitura, marca, formato e unitÃ  restano quelli concordati.
Ogni modifica diventa una SupplierPriceChange con la sua decorrenza (regole in
services/open_price_list_rules.py); il listino viene aggiornato dal job di attivazione.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import require_admin
from app.api.v1.supplier_price_forms import (
    _active_supplier_rows,
    _best_prices,
    _encrypt_token,
    _format_label,
    _offer_formats,
    _require_primary_tenant,
    _token_cipher,
)
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.supplier_price_link import (
    STATI_IN_ATTESA,
    STATO_SOSTITUITO,
    SupplierPriceChange,
    SupplierPriceLink,
    offer_key,
)
from app.models.utenti import Utente
from app.services.open_price_list_rules import decide_change, next_fixed_date, offer_lock_key, today_rome
from app.services.smart_price_purchases import load_purchase_stats_select

router = APIRouter()

TOP_PRODUCTS = 50
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


@router.get("/public/{token}", summary="Listino aperto del fornitore")
async def get_open_price_list(token: str, db: AsyncSession = Depends(get_db)):
    link, supplier_name = await _active_link(db, token)
    today = today_rome()
    rows = await _active_supplier_rows(db, link.fornitore_id)
    formats = await _offer_formats(db, link.fornitore_id, rows)
    skus = {row.sku_interno for row in rows}
    spend = await _spend_by_sku(db, skus, today)
    best = await _best_prices(db, link.fornitore_id, skus)
    pending = await _pending_changes(db, link.fornitore_id)
    ranked = sorted(rows, key=lambda r: (-spend.get(r.sku_interno, Decimal(0)), r.descrizione.casefold()))
    top_skus: list[str] = []
    for row in ranked:
        if spend.get(row.sku_interno, 0) > 0 and row.sku_interno not in top_skus and len(top_skus) < TOP_PRODUCTS:
            top_skus.append(row.sku_interno)
    items = []
    for row in ranked:
        quantity, unit, wording, brand = formats.get(row.id, (None, None, None, None))
        change = pending.get(offer_key(row.sku_interno, row.supplier_product_alias_id))
        items.append({
            "listino_id": row.id,
            "descrizione": row.descrizione,
            "dicitura": wording,
            "marca": brand,
            "formato": _format_label(quantity, unit or (row.unita_misura or "").upper() or None),
            "prezzo": _money(row.prezzo_pattuito),
            "importante": row.sku_interno in top_skus,
            # Solo "siete / non siete i piÃ¹ convenienti": mai il prezzo degli altri.
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
    }


class PriceUpdate(BaseModel):
    listino_id: int
    prezzo: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=4)
    non_trattato: bool = False
    nota: str | None = Field(default=None, max_length=500)


class PriceUpdates(BaseModel):
    modifiche: list[PriceUpdate] = Field(min_length=1, max_length=2000)


@router.post("/public/{token}/submit", summary="Il fornitore invia i prezzi cambiati")
async def submit_open_price_list(token: str, payload: PriceUpdates, request: Request,
                                 db: AsyncSession = Depends(get_db)):
    link, _ = await _active_link(db, token, for_update=True)
    ids = [update.listino_id for update in payload.modifiche]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Lo stesso prodotto compare due volte")
    rows = {row.id: row for row in await _active_supplier_rows(db, link.fornitore_id)}
    now = datetime.now(timezone.utc)
    today = today_rome()
    ip = (request.client.host if request.client else None)
    summary = {"ribassi": 0, "aumenti": 0, "non_trattati": 0, "sospese": 0, "annullate": 0, "invariati": 0}
    for update in payload.modifiche:
        row = rows.get(update.listino_id)
        if row is None:
            raise HTTPException(status_code=409, detail="Un prodotto non Ã¨ piÃ¹ nel vostro listino: ricarica la pagina")
        if update.non_trattato == (update.prezzo is not None):
            raise HTTPException(status_code=422, detail=f"{row.descrizione}: indica un prezzo oppure Â«non lo tratto piÃ¹Â»")
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
            continue  # stessa modifica giÃ  in attesa
        if pending:
            # Conta l'ultimo caricamento: la modifica in attesa Ã¨ superata.
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
        if decision.motivo_trattenuta:
            summary["sospese"] += 1
        summary[{"ribasso": "ribassi", "aumento": "aumenti", "non_trattato": "non_trattati"}[decision.tipo]] += 1
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
