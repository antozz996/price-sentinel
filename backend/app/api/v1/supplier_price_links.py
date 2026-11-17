"""Listino sempre aperto: link fisso con cui il fornitore aggiorna i prezzi.

Il fornitore vede i suoi prezzi validi oggi (i 50 su cui spendiamo di più in alto)
e cambia solo il prezzo: dicitura, marca, formato e unità restano quelli concordati.
Ogni modifica diventa una SupplierPriceChange con la sua decorrenza (regole in
services/open_price_list_rules.py); il listino viene aggiornato dal job di attivazione.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
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
    _require_primary_tenant,
    _token_cipher,
)
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.supplier_price_link import (
    STATI_IN_ATTESA,
    STATO_APPLICATO,
    PROPOSTA_IN_ATTESA,
    PROPOSTA_NOME,
    PROPOSTA_PRODOTTO_NUOVO,
    PROPOSTA_SOSTITUITA,
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
    SupplierProductProposal,
    offer_key,
)
from app.services.normalization import normalize_text
from app.models.utenti import Utente
from app.services.open_price_list_activation import apply_change_now
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
    skus = {row.sku_interno for row in rows}
    spend = await _spend_by_sku(db, skus, today)
    best = await _best_prices(db, link.fornitore_id, skus)
    pending = await _pending_changes(db, link.fornitore_id)
    proposals = await _pending_proposals(db, link.fornitore_id)
    pending_names = {p.listino_id_origine: p.nome_fornitore for p in proposals if p.tipo == PROPOSTA_NOME}
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
            "nome_in_attesa": pending_names.get(row.id),
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
        "prodotti_proposti": [{
            "id": p.id, "nome": p.nome_fornitore, "unita_vendita": p.unita_vendita,
            "contenuto_quantita": _money(p.contenuto_quantita), "contenuto_unita": p.contenuto_unita,
            "prezzo": _money(p.prezzo), "created_at": p.created_at.isoformat(),
        } for p in proposals if p.tipo == PROPOSTA_PRODOTTO_NUOVO],
    }


class PriceUpdate(BaseModel):
    listino_id: int
    prezzo: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=4)
    non_trattato: bool = False
    nota: str | None = Field(default=None, max_length=500)
    # Il nome con cui il fornitore chiama il prodotto (il nostro nome non cambia).
    nome_fornitore: str | None = Field(default=None, max_length=255)


class NewProduct(BaseModel):
    nome: str = Field(min_length=2, max_length=255)
    unita_vendita: str
    contenuto_quantita: Decimal | None = Field(default=None, gt=0, lt=Decimal("1000000"), decimal_places=4)
    contenuto_unita: str | None = None
    prezzo: Decimal = Field(gt=0, lt=Decimal("100000000"), decimal_places=4)


class PriceUpdates(BaseModel):
    modifiche: list[PriceUpdate] = Field(default_factory=list, max_length=2000)
    nuovi: list[NewProduct] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.modifiche and not self.nuovi:
            raise ValueError("Nessuna modifica da inviare")
        return self


def _clean_name(value: str | None) -> str:
    return " ".join((value or "").split())


def validate_new_product(product: NewProduct) -> NewProduct:
    """Controlla i 4 campi del prodotto nuovo: il contenuto serve solo per cartone e cassa."""
    nome = _clean_name(product.nome)
    if len(nome) < 2:
        raise HTTPException(status_code=422, detail="Prodotto nuovo: scrivete il nome")
    unit = (product.unita_vendita or "").strip().upper()
    if unit not in UNITA_VENDITA:
        raise HTTPException(status_code=422, detail=f"{nome}: scegliete come lo vendete")
    if unit in UNITA_CON_CONTENUTO:
        content_unit = (product.contenuto_unita or "").strip().upper()
        if product.contenuto_quantita is None or content_unit not in UNITA_CONTENUTO:
            raise HTTPException(status_code=422, detail=f"{nome}: indicate quanti pezzi o kg ci sono dentro")
        return product.model_copy(update={"nome": nome, "unita_vendita": unit, "contenuto_unita": content_unit})
    return product.model_copy(update={"nome": nome, "unita_vendita": unit,
                                      "contenuto_quantita": None, "contenuto_unita": None})


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


@router.post("/public/{token}/submit", summary="Il fornitore invia i prezzi cambiati")
async def submit_open_price_list(token: str, payload: PriceUpdates, request: Request,
                                 db: AsyncSession = Depends(get_db)):
    link, _ = await _active_link(db, token, for_update=True)
    new_products = [validate_new_product(product) for product in payload.nuovi]
    ids = [update.listino_id for update in payload.modifiche]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Lo stesso prodotto compare due volte")
    rows = {row.id: row for row in await _active_supplier_rows(db, link.fornitore_id)}
    named_rows = [rows[u.listino_id] for u in payload.modifiche if u.nome_fornitore is not None and u.listino_id in rows]
    wording = {row_id: fmt[2] for row_id, fmt in (await _offer_formats(db, link.fornitore_id, named_rows)).items()} \
        if named_rows else {}
    now = datetime.now(timezone.utc)
    today = today_rome()
    ip = (request.client.host if request.client else None)
    summary = {"ribassi": 0, "aumenti": 0, "non_trattati": 0, "sospese": 0, "annullate": 0, "invariati": 0,
               "nomi": 0, "nuovi": 0}
    for update in payload.modifiche:
        row = rows.get(update.listino_id)
        if row is None:
            raise HTTPException(status_code=409, detail="Un prodotto non è più nel vostro listino: ricarica la pagina")
        name = _clean_name(update.nome_fornitore) if update.nome_fornitore is not None else None
        has_price = update.non_trattato or update.prezzo is not None
        if update.non_trattato and update.prezzo is not None:
            raise HTTPException(status_code=422, detail=f"{row.descrizione}: indica un prezzo oppure «non lo tratto più»")
        if not has_price and not name:
            raise HTTPException(status_code=422,
                                detail=f"{row.descrizione}: indica un prezzo, «non lo tratto più» o il vostro nome")
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


@router.get("/overview/count", summary="Contatore del menu: sospese e aumenti in arrivo")
async def price_changes_count(admin: Utente = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _require_primary_tenant(admin)
    count = (await db.execute(select(func.count()).select_from(SupplierPriceChange).where(or_(
        SupplierPriceChange.stato == STATO_TRATTENUTO,
        and_(SupplierPriceChange.stato == STATO_PROGRAMMATO, SupplierPriceChange.tipo == TIPO_AUMENTO),
    )))).scalar_one()
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
    supplier_ids = {c.fornitore_id for c in pending} | {link.fornitore_id for link in links}
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
    increases = sorted((view(c) for c in pending if c.stato == STATO_PROGRAMMATO and c.tipo == TIPO_AUMENTO),
                       key=lambda v: -Decimal(v["impatto_annuo"] or 0))
    decreases = [view(c) for c in pending if c.tipo == TIPO_RIBASSO and c.stato != STATO_TRATTENUTO]
    saving = sum((-Decimal(v["impatto_annuo"]) for v in decreases if v["impatto_annuo"]), Decimal(0))

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
    return {
        "oggi": today.isoformat(),
        "prossima_data_fissa": next_fixed_date(today).isoformat(),
        "contatore": len(held) + len(increases),
        "sospese": held,
        "aumenti": increases,
        "ribassi": {"numero": len(decreases), "risparmio_annuo": _money(saving), "giorni": RIBASSI_GIORNI},
        "solleciti": {"scadenza": deadline.isoformat() if deadline else None, "fornitori": reminders},
        "non_confermati": {"giorni": NON_CONFERMATO_GIORNI, "fornitori": stale},
    }


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
