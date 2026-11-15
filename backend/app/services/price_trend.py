"""Trend storico dei prezzi di una voce (Oscillazioni prezzi e ValidationRoom).

Regole (rapporto schermate 14/11/2026, problemi A5, A6, M29):

- la serie contiene solo le righe di fattura collegate a quello SKU
  (sku_interno uguale, riga abbinata): niente parole chiave né sinonimi, che
  facevano entrare righe di altri prodotti (CAN-... -> "can" su tutto il catalogo);
- le regole comuni vengono da services.purchase_lines: netto = pu x (1 - sconto),
  tenant, skus_esclusi e righe_escluse_statistiche, omaggi fuori;
- ogni punto è convertito nell'unità del listino del fornitore della riga, con
  lo stesso fattore della base comune (line_conversion, strict_pack). Se la
  conversione non è affidabile il punto resta nella sua unità di fattura
  (confrontabile=False) e non entra nella linea;
- il contratto di un punto è il listino dello stesso fornitore valido alla data
  del documento, scelto come matching._get_listino_attivo (data inizio più
  recente; due listini validi lo stesso giorno = nessun contratto);
- le note di credito (TD04/TD08) restano nella serie come resi (is_reso=True),
  da disegnare come marcatori separati, mai come acquisti.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.orm import noload

from app.models.esclusi import SKUEscluso
from app.models.fatture import Fattura, RigaFattura, StatoMatching
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import Product, SupplierProductAlias
from app.services.normalization import unit_family
from app.services.purchase_lines import (
    AliasIndex,
    document_sign,
    line_conversion,
    line_net_unit_price,
    normalized_unit,
    purchase_lines_select,
)

# ─────────────────────────────────────────────
# Parole chiave (solo per il fallback per nome)
# ─────────────────────────────────────────────

_STOP_WORDS = {
    'bev', 'pet', 'per', 'con', 'del', 'dei', 'delle', 'della', 'degli', 'allo', 'alla',
    'alle', 'agli', 'vol', 'cl', 'lt', 'ml', 'gr', 'kg', 'bt', 'pz', 'crt',
    'pac', 'conf', 'cassa', 'bar', 'rist', 'doc', 'dop', 'igp', 'igt', 'san', 'sant',
    'red', 'blue', 'gold', 'plus', 'pro', 'max', 'min', 'net', 'lord', 'art', 'cod',
    'x', 'da', 'di', 'in', 'su', 'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una',
    'sku',
}


def extract_informative_keywords(text: str) -> list[str]:
    """Parole chiave di una descrizione, escluse stop word e unità di misura.

    Un identificativo tecnico (SKU-1111014-515, SG3-..., CAN-...) non è una
    descrizione e non produce parole chiave: prima la regex r"\\d" cercava un
    backslash letterale e "CAN-21-494-1793543248" diventava ["can"].
    """
    if not text:
        return []
    compact_text = text.strip()
    if (
        re.search(r"\d", compact_text)
        and re.search(r"[-_]", compact_text)
        and len(compact_text.split()) <= 2
    ):
        return []
    cleaned = re.sub(r'[^a-zA-Z\s]', ' ', text.lower())
    words = []
    for w in cleaned.split():
        w_s = w.strip()
        if len(w_s) >= 3 and w_s not in _STOP_WORDS and not w_s.endswith(('cl', 'lt', 'ml', 'gr', 'kg')):
            if w_s.startswith(('aranci', 'aranc')):
                words.append('aran')
            elif w_s.startswith('anana'):
                words.append('anan')
            elif w_s.startswith('mirtill'):
                words.append('mirtill')
            elif w_s.startswith('albicoc') or w_s == 'alb':
                words.append('alb')
            elif w_s.startswith('pesc'):
                words.append('pesc')
            else:
                words.append(w_s)
    return list(dict.fromkeys(words))


# ─────────────────────────────────────────────
# Listino valido alla data
# ─────────────────────────────────────────────

def listino_valid_at(listini: Sequence[Any], day: date, alias_id: Optional[int] = None):
    """Listino di un fornitore valido il giorno `day`, con la regola di matching._get_listino_attivo.

    listini: righe ListinoMaster di una sola coppia (sku, fornitore).
    Prima quelli legati al collegamento della riga; due listini validi lo stesso
    giorno sono un prezzo ambiguo e non danno contratto.
    """
    valid = [
        item for item in listini
        if item.data_inizio_validita is not None and item.data_inizio_validita <= day
        and (item.data_scadenza is None or item.data_scadenza >= day)
    ]
    valid.sort(key=lambda item: (item.data_inizio_validita, item.id or 0), reverse=True)
    if alias_id is not None:
        exact = [item for item in valid if item.supplier_product_alias_id == alias_id]
        if len(exact) > 1:
            return None
        if exact:
            return exact[0]
    return valid[0] if len(valid) == 1 else None


def series_unit(listini: Sequence[Any], today: Optional[date] = None) -> Optional[str]:
    """Unità del contratto attuale del fornitore (None = unità della voce).

    Serve per i punti senza un listino valido alla loro data (acquisti prima del
    primo listino, o due listini validi insieme): restano nell'unità del listino
    ancora aperto più recente, altrimenti dell'ultimo scaduto.
    """
    if not listini:
        return None
    today = today or date.today()
    latest = max(listini, key=lambda item: (
        item.data_scadenza is None or item.data_scadenza >= today,
        item.data_inizio_validita or date.min,
        item.id or 0,
    ))
    return latest.unita_misura or None


def contract_unit(listino: Any, product: Optional[Product]) -> Optional[str]:
    """Unità di confronto di un listino: la sua, altrimenti quella della voce (come il matching)."""
    if listino is None:
        return None
    return unit_family(listino.unita_misura or (product.comparison_unit if product else None))


def _round(value: Optional[Decimal], digits: int = 4) -> Optional[float]:
    return None if value is None else float(round(Decimal(value), digits))


# ─────────────────────────────────────────────
# Un punto del trend
# ─────────────────────────────────────────────

def trend_point(
    row: Any,
    *,
    product: Optional[Product],
    alias: Optional[SupplierProductAlias],
    supplier_listini: Sequence[Any],
    today: Optional[date] = None,
) -> dict:
    """Punto del trend per una riga di purchase_lines_select (con fornitore_nome e location_nome).

    prezzo_pagato è il netto convertito nell'unità del listino del fornitore
    (None se la conversione non è affidabile: in quel caso vale prezzo_fattura
    per unita_fattura); prezzo_contratto è il listino dello stesso fornitore
    valido alla data del documento, nella stessa unità di prezzo_pagato.
    """
    listino = listino_valid_at(supplier_listini, row.data_documento, alias.id if alias is not None else None)
    target = (listino.unita_misura or None) if listino is not None else series_unit(supplier_listini, today)
    conversion = line_conversion(
        product=product,
        alias=alias,
        unita_misura=row.unita_misura,
        descrizione=row.descrizione,
        target_unit=target,
    )
    netto = line_net_unit_price(row.prezzo_unitario, row.sconto_percentuale)
    converted = conversion.unit_price(netto)
    reliable = converted is not None
    tipo = getattr(row.tipo_documento, "value", row.tipo_documento)
    data_doc = row.data_documento
    return {
        "data": data_doc.isoformat() if isinstance(data_doc, date) else str(data_doc),
        "riga_id": row.riga_id,
        "tipo_documento": tipo,
        "is_reso": document_sign(tipo) == -1,
        "prezzo_fattura": _round(netto),
        "unita_fattura": normalized_unit(row.unita_misura),
        "prezzo_pagato": _round(converted) if reliable else None,
        "unita_confronto": conversion.comparison_unit,
        "confrontabile": reliable,
        "quantita": _round(Decimal(str(row.quantita or 0))),
        "quantita_confronto": _round(conversion.quantity(row.quantita or 0)) if reliable else None,
        "fornitore_id": row.fornitore_id,
        "fornitore": row.fornitore_nome,
        "location": row.location_nome,
        "prezzo_contratto": _round(Decimal(str(listino.prezzo_pattuito))) if listino is not None and listino.prezzo_pattuito is not None else None,
        "fattura_id": row.fattura_id,
        "numero_documento": row.numero_documento,
    }


def series_summary(
    key: str,
    *,
    product: Optional[Product],
    history: list[dict],
    listini_by_supplier: Mapping[int, Sequence[Any]],
    requested_suppliers: Optional[Iterable[int]],
    today: date,
    fallback_name: Optional[str] = None,
) -> dict:
    """Intestazione della serie: contratto corrente solo se il fornitore è uno solo."""
    supplier_names: dict[int, str] = {}
    for point in history:
        supplier_names.setdefault(point["fornitore_id"], point["fornitore"])
    requested = set(requested_suppliers or [])
    if history:
        suppliers = list(supplier_names)
    elif requested:
        suppliers = sorted(requested)
    else:
        suppliers = sorted(
            fid for fid, items in listini_by_supplier.items() if listino_valid_at(items, today) is not None
        )

    fornitori = []
    for fid in suppliers:
        current = listino_valid_at(listini_by_supplier.get(fid, ()), today)
        fornitori.append({
            "fornitore_id": fid,
            "fornitore": supplier_names.get(fid),
            "prezzo_contratto_corrente": _round(Decimal(str(current.prezzo_pattuito))) if current is not None else None,
            "unita_contratto": contract_unit(current, product),
        })

    single = fornitori[0] if len(fornitori) == 1 else None
    name = (product.canonical_name if product is not None else None) or fallback_name or key
    return {
        "sku_interno": product.sku_interno if product is not None else key,
        "prodotto_nome": name,
        "prezzo_contratto_corrente": single["prezzo_contratto_corrente"] if single else None,
        "unita_contratto_corrente": single["unita_contratto"] if single else None,
        "fornitori": fornitori,
        "history": history,
    }


# ─────────────────────────────────────────────
# Caricamento dal database
# ─────────────────────────────────────────────

async def _resolve_products(db, keys: list[str]) -> dict[str, Optional[Product]]:
    """SKU richiesto -> voce. Per nome solo se nessuna voce ha quello SKU e il nome indica una voce sola."""
    lowered = {key.lower().strip(): key for key in keys}
    found: dict[str, Optional[Product]] = {key: None for key in keys}
    by_sku = (await db.scalars(
        select(Product).options(noload("*")).where(func.lower(func.trim(Product.sku_interno)).in_(list(lowered)))
    )).all()
    for product in by_sku:
        key = lowered.get((product.sku_interno or "").lower().strip())
        if key is not None:
            found[key] = product

    for key in [k for k, v in found.items() if v is None]:
        exact = (await db.scalars(
            select(Product).options(noload("*")).where(
                func.lower(func.trim(Product.canonical_name)) == key.lower().strip(),
                Product.sku_interno.isnot(None),
            ).limit(2)
        )).all()
        if len(exact) == 1:
            found[key] = exact[0]
            continue
        keywords = extract_informative_keywords(key)
        if len(keywords) < 2:
            continue
        candidates = (await db.scalars(
            select(Product).options(noload("*")).where(
                and_(*[Product.canonical_name.ilike(f"%{kw}%") for kw in keywords]),
                Product.sku_interno.isnot(None),
            ).limit(2)
        )).all()
        if len(candidates) == 1:
            found[key] = candidates[0]
    return found


def trend_lines_select(
    user,
    skus: Sequence[str],
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    location_ids: Optional[list[int]] = None,
    fornitore_ids: Optional[list[int]] = None,
):
    """Righe del trend: SOLO quelle collegate agli SKU dati (uguaglianza, nessun LIKE), abbinate e pagate."""
    return (
        purchase_lines_select(
            user,
            date_from=start_date,
            date_to=end_date,
            location_ids=location_ids,
            fornitore_ids=fornitore_ids,
            skus=list(skus),
            require_sku=True,
        )
        .add_columns(
            func.coalesce(Fornitore.nome_azienda, "Fornitore non associato").label("fornitore_nome"),
            func.coalesce(Location.nome_struttura, "Tutte le sedi").label("location_nome"),
        )
        .outerjoin(Fornitore, Fornitore.id == Fattura.fornitore_id)
        .outerjoin(Location, Location.id == Fattura.location_id)
        .where(
            RigaFattura.stato_matching == StatoMatching.matched,
            RigaFattura.prezzo_unitario_fatturato > 0,
        )
        .order_by(Fattura.data_documento.asc(), RigaFattura.id.asc())
    )


async def load_price_trends(
    db,
    user,
    sku_list: list[str],
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    location_ids: Optional[list[int]] = None,
    fornitore_ids: Optional[list[int]] = None,
    today: Optional[date] = None,
) -> dict[str, dict]:
    """Trend per ogni SKU richiesto (chiave = SKU come richiesto)."""
    if not sku_list:
        return {}
    excluded = {
        (s or "").lower().strip()
        for s in (await db.scalars(
            select(SKUEscluso.sku_interno).where(
                func.lower(func.trim(SKUEscluso.sku_interno)).in_([s.lower().strip() for s in sku_list])
            )
        )).all()
    }
    keys = [s for s in sku_list if s.lower().strip() not in excluded]
    if not keys:
        return {}

    products_by_key = await _resolve_products(db, keys)
    sku_by_key = {
        key: (product.sku_interno if product is not None else key)
        for key, product in products_by_key.items()
    }
    if any((sku or "").lower().strip() in excluded for sku in sku_by_key.values()):
        sku_by_key = {k: v for k, v in sku_by_key.items() if (v or "").lower().strip() not in excluded}
    target_skus = sorted(set(sku_by_key.values()))
    if not target_skus:
        return {}

    stmt = trend_lines_select(
        user,
        target_skus,
        start_date=start_date,
        end_date=end_date,
        location_ids=location_ids,
        fornitore_ids=fornitore_ids,
    )
    rows = [row for row in (await db.execute(stmt)).all() if not row.is_omaggio]

    product_ids = {row.product_id for row in rows if row.product_id is not None}
    product_ids |= {p.id for p in products_by_key.values() if p is not None}
    products: dict[int, Product] = {}
    if product_ids:
        products = {
            p.id: p for p in (await db.scalars(
                select(Product).options(noload("*")).where(Product.id.in_(product_ids))
            )).all()
        }
    aliases = []
    if product_ids:
        aliases = (await db.scalars(
            select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.product_id.in_(product_ids))
        )).all()
    alias_index = AliasIndex(aliases)

    listini_rows = (await db.scalars(
        select(ListinoMaster).options(noload("*")).where(ListinoMaster.sku_interno.in_(target_skus))
    )).all()
    listini: dict[tuple[str, int], list] = {}
    for item in listini_rows:
        listini.setdefault((item.sku_interno, item.fornitore_id), []).append(item)

    today = today or date.today()
    points_by_sku: dict[str, list[dict]] = {sku: [] for sku in target_skus}
    first_description: dict[str, str] = {}
    for row in rows:
        product = products.get(row.product_id) if row.product_id is not None else None
        alias = alias_index.resolve(row.fornitore_id, row.product_id, row.codice_fornitore, row.descrizione)
        points_by_sku.setdefault(row.sku_interno, []).append(trend_point(
            row,
            product=product,
            alias=alias,
            supplier_listini=listini.get((row.sku_interno, row.fornitore_id), ()),
            today=today,
        ))
        if row.descrizione:
            first_description.setdefault(row.sku_interno, row.descrizione)

    response: dict[str, dict] = {}
    for key, sku in sku_by_key.items():
        product = products_by_key.get(key)
        if product is not None:
            product = products.get(product.id, product)
        by_supplier = {fid: items for (s, fid), items in listini.items() if s == sku}
        response[key] = series_summary(
            key,
            product=product,
            history=points_by_sku.get(sku, []),
            listini_by_supplier=by_supplier,
            requested_suppliers=fornitore_ids,
            today=today,
            fallback_name=first_description.get(sku),
        )
    return response
