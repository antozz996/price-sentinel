"""
Price Sentinel - Analisi volumi di acquisto (sola lettura).

Quante unita' di un prodotto sono state acquistate in un periodo, per fonte:
- ``fatture`` (default): merce realmente ricevuta e pagata (righe_fattura).
- ``ordini``: merce richiesta ai fornitori (righe_ordine).

Le quantita' non vengono mai sommate tra unita' diverse. Una conversione verso
l'unita' di confronto del prodotto (``products.comparison_unit``) viene
applicata solo quando e' affidabile; altrimenti resta la quantita' grezza con
la sua unita'.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import Date, and_, case, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import require_admin
from app.database import get_db
from app.models.esclusi import SKUEscluso
from app.models.fatture import Fattura, RigaFattura, TipoDocumento
from app.models.fornitori import Fornitore
from app.models.ordini import Ordine, RigaOrdine
from app.models.products import Product, SupplierProductAlias
from app.services.matching import normalize_price_for_comparison
from app.services.normalization import KG_UNITS, normalize_text
from app.services.tenant_scope import DEFAULT_TENANT_ID, invoice_tenant_filter, user_tenant_id

router = APIRouter()

_EMPTY = literal_column("''")

Fonte = Literal["fatture", "ordini"]
Granularita = Literal["settimana", "mese"]

_LITER = {"l", "lt", "liter", "litre", "litro", "litri"}
_BOX = {
    "cassa", "casse", "cartone", "cartoni", "box", "conf", "confezione",
    "confezioni", "cf", "cnf", "crt", "css", "ct", "cs",
}
_PIECE = {
    "piece", "pieces", "pezzo", "pezzi", "pz", "unita", "unit",
    "bottle", "bottiglia", "bottiglie", "bot", "bt", "btl", "fl",
}


def _family(unit: str | None) -> str | None:
    """Famiglia di misura di un'unita' (piece/box/kg/liter) o None se ignota."""
    u = normalize_text(str(unit or ""))
    if not u:
        return None
    if u in KG_UNITS:
        return "kg"
    if u in _LITER:
        return "liter"
    if u in _BOX:
        return "box"
    if u in _PIECE:
        return "piece"
    return None


def conversion_factor(uom: str | None, product: Product | None, alias: SupplierProductAlias | None) -> Decimal | None:
    """
    Fattore per portare 1 ``uom`` nell'unita' di confronto del prodotto, o None.

    Usa ``normalize_price_for_comparison`` su un prezzo unitario di 1: il prezzo
    normalizzato e' il costo di 1 unita' di confronto, quindi il fattore e' il suo
    inverso. Guardie aggiuntive scartano le conversioni che la funzione considera
    affidabili solo perche' il pack mancante vale 1 per default.
    """
    if product is None or not product.comparison_unit:
        return None
    src = _family(uom)
    dst = _family(product.comparison_unit)
    if src is None or dst is None:
        return None
    if src == dst:
        return Decimal(1)
    if src in ("kg", "liter"):
        # Peso o volume non diventano pezzi/confezioni senza dati certi.
        return None
    explicit_pack = None
    if alias is not None and alias.pack_qty is not None:
        explicit_pack = alias.pack_qty
    elif product.unit_count is not None:
        explicit_pack = product.unit_count
    needs_pack = src == "box" or dst == "box"
    if needs_pack and not (explicit_pack and explicit_pack > 1):
        return None
    result = normalize_price_for_comparison(Decimal(1), Decimal(1), uom, product, alias)
    if not result.reliable or not result.normalized_unit_price or result.normalized_unit_price <= 0:
        return None
    # Quantizzato per evitare residui come 5,999... da 1 / (1/6).
    return (Decimal(1) / Decimal(result.normalized_unit_price)).quantize(Decimal("0.000001"))


# ─────────────────────────────────────────────
# Query
# ─────────────────────────────────────────────

@dataclass
class Filtri:
    fonte: str
    data_da: date
    data_a: date
    q: str | None
    categoria: str | None
    sottocategoria: str | None
    fornitore_id: int | None
    sku: str | None = None


def _filtri(
    fonte: Fonte = Query("fatture", description="fatture = ricevuto/pagato, ordini = richiesto"),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    q: str | None = Query(None, max_length=120, description="Ricerca per nome o SKU"),
    categoria: str | None = Query(None, max_length=100),
    sottocategoria: str | None = Query(None, max_length=100),
    fornitore_id: int | None = Query(None),
) -> Filtri:
    data_a = data_a or date.today()
    data_da = data_da or (data_a - timedelta(days=29))
    if data_da > data_a:
        raise HTTPException(status_code=422, detail="La data iniziale deve precedere quella finale")
    return Filtri(
        fonte=fonte,
        data_da=data_da,
        data_a=data_a,
        q=(q or "").strip() or None,
        categoria=(categoria or "").strip() or None,
        sottocategoria=(sottocategoria or "").strip() or None,
        fornitore_id=fornitore_id,
    )


def _product_keys(f: Filtri, with_query: bool):
    conds = [Product.sku_interno.isnot(None)]
    if f.categoria:
        conds.append(Product.category == f.categoria)
    if f.sottocategoria:
        conds.append(Product.subcategory == f.sottocategoria)
    if with_query and f.q:
        conds.append(Product.canonical_name.icontains(f.q, autoescape=True))
    return select(func.lower(func.trim(Product.sku_interno))).where(*conds)


def _group_statement(f: Filtri, user, granularita: str | None = None):
    if f.fonte == "ordini":
        sku_col, descr_col = RigaOrdine.sku_interno, RigaOrdine.descrizione
        uom_col = RigaOrdine.uom
        day = cast(Ordine.data_ordine, Date)
        price = RigaOrdine.prezzo_inserito
        qty = RigaOrdine.quantita
        supplier = Ordine.fornitore_id
        doc_id = Ordine.id
        code = None  # gli ordini non riportano il codice articolo del fornitore
        omaggio = None
        tenant_id = user_tenant_id(user)
        tenant_cond = Ordine.tenant_id == tenant_id
        if tenant_id == DEFAULT_TENANT_ID:
            tenant_cond = or_(tenant_cond, Ordine.tenant_id.is_(None))
        base_from = RigaOrdine.__table__.join(Ordine.__table__, RigaOrdine.ordine_id == Ordine.id)
        extra = [tenant_cond]
    else:
        sku_col, descr_col = RigaFattura.sku_interno, RigaFattura.descrizione_fornitore_raw
        uom_col = RigaFattura.unita_misura_fattura
        day = Fattura.data_documento
        price = RigaFattura.prezzo_unitario_fatturato * (
            1 - func.coalesce(RigaFattura.sconto_percentuale, 0) / 100
        )
        qty = RigaFattura.quantita
        supplier = Fattura.fornitore_id
        doc_id = Fattura.id
        code = func.coalesce(func.upper(func.trim(RigaFattura.codice_fornitore_raw)), _EMPTY)
        omaggio = RigaFattura.is_omaggio.is_(True)
        base_from = RigaFattura.__table__.join(Fattura.__table__, RigaFattura.fattura_id == Fattura.id)
        # Le note di credito non sono acquisti: le quantita' resterebbero ambigue.
        extra = [invoice_tenant_filter(user), Fattura.tipo_documento != TipoDocumento.TD04]

    sku_key = func.lower(func.trim(sku_col))
    uom = func.upper(func.trim(func.coalesce(uom_col, _EMPTY)))
    free = omaggio if omaggio is not None else False
    paid = and_(~free, price > 0) if omaggio is not None else price > 0

    columns = [
        sku_key.label("sku_key"),
        func.max(sku_col).label("sku"),
        func.max(descr_col).label("descrizione"),
        supplier.label("fornitore_id"),
        uom.label("uom"),
        func.sum(qty).label("qty"),
        func.sum(case((paid, qty), else_=0)).label("qty_pagata"),
        func.sum(case((paid, price * qty), else_=0)).label("spesa"),
        func.count().label("righe"),
        func.array_agg(func.distinct(doc_id)).label("docs"),
    ]
    if omaggio is not None:
        columns.append(func.sum(case((omaggio, qty), else_=0)).label("qty_omaggio"))
    group_by = [sku_key, supplier, uom]
    if code is not None:
        columns.append(code.label("code"))
        group_by.append(code)
    if granularita:
        # Costanti inline: con parametri separati PostgreSQL non riconoscerebbe
        # la stessa espressione in SELECT e GROUP BY.
        unit = literal_column("'week'" if granularita == "settimana" else "'month'")
        period = cast(func.date_trunc(unit, day), Date)
        columns.append(period.label("periodo"))
        group_by.append(period)

    conds = [
        sku_col.isnot(None),
        func.trim(sku_col) != "",
        sku_col.notin_(select(SKUEscluso.sku_interno)),
        day >= f.data_da,
        day <= f.data_a,
        *extra,
    ]
    if f.fornitore_id:
        conds.append(supplier == f.fornitore_id)
    if f.sku:
        conds.append(sku_key == f.sku.strip().lower())
    if f.categoria or f.sottocategoria:
        conds.append(sku_key.in_(_product_keys(f, with_query=False)))
    if f.q:
        conds.append(or_(
            sku_key.in_(_product_keys(f, with_query=True)),
            descr_col.icontains(f.q, autoescape=True),
            sku_col.icontains(f.q, autoescape=True),
        ))
    return select(*columns).select_from(base_from).where(*conds).group_by(*group_by)


async def _load(db: AsyncSession, f: Filtri, user, granularita: str | None = None):
    rows = (await db.execute(_group_statement(f, user, granularita))).all()
    keys = {r.sku_key for r in rows}
    products: dict[str, Product] = {}
    aliases: dict[tuple[int, int], list[SupplierProductAlias]] = {}
    suppliers: dict[int, str] = {}
    if keys:
        found = (await db.execute(
            select(Product).options(noload("*"))
            .where(func.lower(func.trim(Product.sku_interno)).in_(keys))
            .order_by(Product.is_active.desc(), Product.id)
        )).scalars().all()
        for p in found:
            products.setdefault(p.sku_interno.strip().lower(), p)
        product_ids = [p.id for p in products.values()]
        if product_ids:
            for a in (await db.execute(
                select(SupplierProductAlias).options(noload("*"))
                .where(SupplierProductAlias.product_id.in_(product_ids),
                       SupplierProductAlias.status == "approved")
            )).scalars().all():
                aliases.setdefault((a.supplier_id, a.product_id), []).append(a)
        supplier_ids = {r.fornitore_id for r in rows}
        suppliers = dict((await db.execute(
            select(Fornitore.id, Fornitore.nome_azienda).where(Fornitore.id.in_(supplier_ids))
        )).all())
    return rows, products, aliases, suppliers


def _alias_for(row, product: Product | None, aliases) -> SupplierProductAlias | None:
    """Alias usato solo se identifica il formato senza ambiguita'."""
    if product is None:
        return None
    candidates = aliases.get((row.fornitore_id, product.id), [])
    code = (getattr(row, "code", None) or "").strip().upper()
    if code:
        by_code = [a for a in candidates if (a.supplier_code or "").strip().upper() == code]
        if len(by_code) == 1:
            return by_code[0]
        if by_code:
            return None
    if len(candidates) == 1 and not (code and candidates[0].supplier_code):
        return candidates[0]
    return None


# ─────────────────────────────────────────────
# Aggregazione
# ─────────────────────────────────────────────

@dataclass
class Bucket:
    per_unita: dict[str, Decimal] = field(default_factory=dict)
    qty_norm: Decimal = Decimal(0)
    qty_norm_pagata: Decimal = Decimal(0)
    qty_pagata_per_unita: dict[str, Decimal] = field(default_factory=dict)
    convertibile: bool = True
    righe: int = 0
    docs: set = field(default_factory=set)
    spesa: Decimal = Decimal(0)
    omaggio: Decimal = Decimal(0)

    def add(self, row, factor: Decimal | None) -> None:
        unit = row.uom or "N.D."
        qty = Decimal(row.qty or 0)
        qty_paid = Decimal(row.qty_pagata or 0)
        self.per_unita[unit] = self.per_unita.get(unit, Decimal(0)) + qty
        self.qty_pagata_per_unita[unit] = self.qty_pagata_per_unita.get(unit, Decimal(0)) + qty_paid
        if factor is None:
            self.convertibile = False
        else:
            self.qty_norm += qty * factor
            self.qty_norm_pagata += qty_paid * factor
        self.righe += int(row.righe or 0)
        self.docs.update(row.docs or [])
        self.spesa += Decimal(row.spesa or 0)
        self.omaggio += Decimal(getattr(row, "qty_omaggio", 0) or 0)

    def out(self, unita_confronto: str | None) -> dict:
        norm = self.convertibile and unita_confronto is not None
        prezzo, unita_prezzo = None, None
        if norm and self.qty_norm_pagata > 0:
            prezzo, unita_prezzo = self.spesa / self.qty_norm_pagata, unita_confronto
        elif len(self.per_unita) == 1:
            unit = next(iter(self.per_unita))
            if self.qty_pagata_per_unita[unit] > 0:
                prezzo, unita_prezzo = self.spesa / self.qty_pagata_per_unita[unit], unit
        return {
            "quantita_per_unita": [
                {"unita": u, "quantita": round(float(q), 3)}
                for u, q in sorted(self.per_unita.items(), key=lambda kv: -kv[1])
            ],
            "quantita_normalizzata": round(float(self.qty_norm), 3) if norm else None,
            "unita_normalizzata": unita_confronto if norm else None,
            "quantita_omaggio": round(float(self.omaggio), 3),
            "righe": self.righe,
            "documenti": len(self.docs),
            "spesa_totale": round(float(self.spesa), 2),
            "prezzo_medio": round(float(prezzo), 4) if prezzo is not None else None,
            "prezzo_medio_unita": unita_prezzo,
        }


def _aggregate_products(rows, products, aliases, suppliers) -> list[dict]:
    per_product: dict[str, dict] = {}
    for row in rows:
        product = products.get(row.sku_key)
        factor = conversion_factor(row.uom, product, _alias_for(row, product, aliases))
        entry = per_product.setdefault(row.sku_key, {
            "row": row, "total": Bucket(), "suppliers": {},
        })
        entry["total"].add(row, factor)
        entry["suppliers"].setdefault(row.fornitore_id, Bucket()).add(row, factor)

    result = []
    for key, entry in per_product.items():
        product = products.get(key)
        unit = product.comparison_unit if product and product.comparison_unit else None
        row = entry["row"]
        item = {
            "sku_interno": product.sku_interno if product else row.sku,
            "product_id": product.id if product else None,
            "nome": product.canonical_name if product else (row.descrizione or row.sku),
            "categoria": product.category if product else None,
            "sottocategoria": product.subcategory if product else None,
            "unita_confronto": unit,
            **entry["total"].out(unit),
            "fornitori": sorted(
                (
                    {"fornitore_id": sid, "nome": suppliers.get(sid) or f"Fornitore {sid}", **b.out(unit)}
                    for sid, b in entry["suppliers"].items()
                ),
                key=lambda s: -s["spesa_totale"],
            ),
        }
        result.append(item)
    result.sort(key=lambda i: -i["spesa_totale"])
    return result


# ─────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────

@router.get("/opzioni", summary="Opzioni filtri analisi volumi")
async def get_volume_options(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    fornitori = (await db.execute(
        select(Fornitore.id, Fornitore.nome_azienda)
        .where(Fornitore.archived_at.is_(None))
        .order_by(Fornitore.nome_azienda)
    )).all()
    cats = (await db.execute(
        select(Product.category, Product.subcategory)
        .where(Product.category.isnot(None), Product.category != "")
        .distinct()
    )).all()
    categorie: dict[str, set[str]] = {}
    for cat, sub in cats:
        categorie.setdefault(cat, set())
        if sub:
            categorie[cat].add(sub)
    return {
        "fornitori": [{"id": i, "nome": n} for i, n in fornitori],
        "categorie": [
            {"nome": c, "sottocategorie": sorted(s)} for c, s in sorted(categorie.items())
        ],
    }


@router.get("", summary="Analisi volumi di acquisto per prodotto")
async def get_volumes(
    f: Filtri = Depends(_filtri),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows, products, aliases, suppliers = await _load(db, f, _admin)
    return {
        "fonte": f.fonte,
        "data_da": f.data_da.isoformat(),
        "data_a": f.data_a.isoformat(),
        "prodotti": _aggregate_products(rows, products, aliases, suppliers),
    }


@router.get("/dettaglio", summary="Andamento volumi di un prodotto per settimana o mese")
async def get_volume_detail(
    sku: str = Query(..., min_length=1, max_length=100),
    granularita: Granularita = Query("settimana"),
    f: Filtri = Depends(_filtri),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    f.sku = sku
    rows, products, aliases, _ = await _load(db, f, _admin, granularita)
    product = products.get(sku.strip().lower())
    unit = product.comparison_unit if product and product.comparison_unit else None
    periods: dict[date, Bucket] = {}
    for row in rows:
        factor = conversion_factor(row.uom, product, _alias_for(row, product, aliases))
        periods.setdefault(row.periodo, Bucket()).add(row, factor)
    return {
        "sku_interno": product.sku_interno if product else sku,
        "nome": product.canonical_name if product else (rows[0].descrizione if rows else sku),
        "unita_confronto": unit,
        "granularita": granularita,
        "periodi": [
            {"periodo": p.isoformat(), **periods[p].out(unit)} for p in sorted(periods)
        ],
    }


def _num(value) -> str:
    return "" if value is None else f"{value}".replace(".", ",")


@router.get("/export.csv", summary="Esporta analisi volumi in CSV")
async def export_volumes_csv(
    f: Filtri = Depends(_filtri),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows, products, aliases, suppliers = await _load(db, f, _admin)
    data = _aggregate_products(rows, products, aliases, suppliers)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([
        "SKU", "Prodotto", "Categoria", "Sottocategoria", "Fornitore",
        "Quantita per unita", "Quantita normalizzata", "Unita normalizzata",
        "Righe", "Documenti", "Spesa totale", "Prezzo medio", "Unita prezzo",
    ])
    for item in data:
        for scope in [{"nome": "Tutti i fornitori", **item}, *item["fornitori"]]:
            writer.writerow([
                item["sku_interno"], item["nome"], item["categoria"] or "", item["sottocategoria"] or "",
                scope["nome"],
                " + ".join(f"{_num(q['quantita'])} {q['unita']}" for q in scope["quantita_per_unita"]),
                _num(scope["quantita_normalizzata"]), scope["unita_normalizzata"] or "",
                scope["righe"], scope["documenti"], _num(scope["spesa_totale"]),
                _num(scope["prezzo_medio"]), scope["prezzo_medio_unita"] or "",
            ])
    filename = f"analisi_volumi_{f.fonte}_{f.data_da.isoformat()}_{f.data_a.isoformat()}.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
