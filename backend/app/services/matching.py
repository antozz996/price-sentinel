"""
Price Sentinel — Motore di Matching v2 con Master Product Identity Layer.
Sprint 6: Pipeline per abbinamento righe fattura → prodotti canonici → listino master.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Optional, List, Dict, Any
import json

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alias import AliasProdotto
from app.models.listino import ListinoMaster, UoMConversione
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.services.normalization import (
    normalize_text,
    extract_candidate_attributes,
    extract_volume_ml,
    extract_weight_g,
    extract_pack_qty,
    extract_container_type,
)


@dataclass
class MatchResult:
    """Risultato del matching per una singola riga fattura."""
    matched: bool = False
    livello: int = 0               # 1-4
    sku_interno: str | None = None
    listino_id: int | None = None
    prezzo_listino: Decimal = Decimal("0")
    prezzo_fatturato_normalizzato: Decimal = Decimal("0")
    delta_prezzo: Decimal = Decimal("0")      # Differenza per unità
    delta_totale: Decimal = Decimal("0")      # Delta * quantità
    coefficiente_uom: Decimal = Decimal("1")  # Conversione UoM applicata
    confidenza: float = 0.0                   # 0-1 per fuzzy match
    suggerimento_sku: str | None = None       # Per Livello 3
    suggerimento_desc: str | None = None      # Descrizione del suggerimento

    # Nuovi campi Fase 3/4
    product_id: int | None = None
    supplier_alias_id: int | None = None
    score: float = 0.0
    decision: str = "parking"                  # auto_match, needs_review, parking
    reason: str | None = None                  # Dettaglio in JSON
    candidates: list = None                    # Voci candidate suggerite


@dataclass
class NormalizedPriceResult:
    normalized_unit_price: Decimal
    comparison_unit: str
    pack_qty: Optional[int]
    reliable: bool = True
    explanation: str = ""


def normalize_price_for_comparison(
    price_or_line,
    quantity_or_product,
    invoice_uom: Optional[str] = None,
    product: Optional[Product] = None,
    alias: Optional[SupplierProductAlias] = None,
) -> NormalizedPriceResult:
    """
    Normalizza il prezzo di acquisto unitario per consentire il confronto con il listino.
    """
    from decimal import Decimal
    from app.models.products import Product, SupplierProductAlias
    from app.services.normalization import extract_pack_qty, extract_volume_ml, extract_weight_g

    if isinstance(quantity_or_product, Product):
        # Vecchia firma: (invoice_line, product)
        invoice_line = price_or_line
        product_obj = quantity_or_product
        raw_price = getattr(invoice_line, "prezzo_unitario_fatturato", 0) or 0
        discount = getattr(invoice_line, "sconto_percentuale", 0) or 0
        price = Decimal(str(raw_price)) * (Decimal("1") - Decimal(str(discount)) / Decimal("100"))
        quantity = Decimal(str(getattr(invoice_line, "quantita", 1) or 1))
        uom = getattr(invoice_line, "unita_misura_fattura", "") or ""
        descrizione = getattr(invoice_line, "descrizione_fornitore_raw", "") or ""
        alias_obj = alias
    else:
        # Nuova firma: (price, quantity, invoice_uom, product, alias)
        price = Decimal(str(price_or_line))
        quantity = Decimal(str(quantity_or_product))
        uom = invoice_uom
        product_obj = product
        alias_obj = alias
        descrizione = ""
        if alias_obj:
            descrizione = getattr(alias_obj, "raw_description", "") or ""

    if not product_obj:
        return NormalizedPriceResult(
            normalized_unit_price=price,
            comparison_unit="piece",
            pack_qty=1,
            reliable=False,
            explanation="Prodotto canonico mancante",
        )

    comp_unit = product_obj.comparison_unit
    unit_count = product_obj.unit_count or 1

    # 1. Risolvi pack_qty
    pack_qty = None
    if alias_obj and getattr(alias_obj, "pack_qty", None) is not None:
        pack_qty = alias_obj.pack_qty
    if pack_qty is None and product_obj.unit_count is not None:
        pack_qty = product_obj.unit_count
    if pack_qty is None:
        pack_qty = extract_pack_qty(descrizione)
    if pack_qty is None or pack_qty <= 0:
        pack_qty = 1

    reliable = True
    explanation = f"Normalizzazione per {comp_unit}"
    normalized_price = price

    if comp_unit in ("piece", "bottle"):
        # Prezzo al pezzo o bottiglia = prezzo confezione / pack_qty
        uom_lower = (uom or "").lower()
        is_package_uom = any(x in uom_lower for x in ("cassa", "cartone", "box", "conf", "crt", "css", "x"))
        if is_package_uom or pack_qty > 1:
            normalized_price = price / Decimal(str(pack_qty))
        explanation = f"Prezzo unitario normalizzato su confezione da {pack_qty} {comp_unit}"

    elif comp_unit == "liter":
        vol_ml = None
        if alias_obj and getattr(alias_obj, "volume_ml", None) is not None:
            vol_ml = alias_obj.volume_ml
        if vol_ml is None and product_obj.volume_ml is not None:
            vol_ml = product_obj.volume_ml
        if vol_ml is None:
            vol_ml = extract_volume_ml(descrizione)

        if vol_ml:
            uom_lower = (uom or "").lower()
            is_package_uom = any(x in uom_lower for x in ("cassa", "cartone", "box", "conf", "crt", "css", "piece", "pz", "fl", "bt"))
            if is_package_uom and pack_qty > 1:
                prezzo_singolo = price / Decimal(str(pack_qty))
            else:
                prezzo_singolo = price
            normalized_price = prezzo_singolo / (Decimal(str(vol_ml)) / Decimal("1000"))
            explanation = f"Prezzo al litro ricavato da {vol_ml}ml (confezione x{pack_qty})"
        else:
            reliable = False
            explanation = "Volume mancante per calcolo prezzo al litro"

    elif comp_unit == "kg":
        weight_g = None
        if alias_obj and getattr(alias_obj, "weight_g", None) is not None:
            weight_g = alias_obj.weight_g
        if weight_g is None and product_obj.weight_g is not None:
            weight_g = product_obj.weight_g
        if weight_g is None:
            weight_g = extract_weight_g(descrizione)

        if weight_g:
            uom_lower = (uom or "").lower()
            is_package_uom = any(x in uom_lower for x in ("cassa", "cartone", "box", "conf", "crt", "css"))
            if is_package_uom and pack_qty > 1:
                prezzo_singolo = price / Decimal(str(pack_qty))
            else:
                prezzo_singolo = price
            normalized_price = prezzo_singolo / (Decimal(str(weight_g)) / Decimal("1000"))
            explanation = f"Prezzo al kg ricavato da {weight_g}g (confezione x{pack_qty})"
        else:
            reliable = False
            explanation = "Peso mancante per calcolo prezzo al kg"

    elif comp_unit == "box":
        uom_lower = (uom or "").lower()
        is_package_uom = any(x in uom_lower for x in ("cassa", "cartone", "box", "conf", "crt", "css"))
        if not is_package_uom and pack_qty > 1:
            normalized_price = price * Decimal(str(pack_qty))
            explanation = f"Prezzo cassa normalizzato da pezzo singolo x{pack_qty}"

    return NormalizedPriceResult(
        normalized_unit_price=normalized_price,
        comparison_unit=comp_unit,
        pack_qty=pack_qty,
        reliable=reliable,
        explanation=explanation,
    )


async def resolve_invoice_line_product(
    db: AsyncSession,
    fornitore_id: int,
    raw_description: str,
    supplier_code: Optional[str] = None,
    ean: Optional[str] = None,
) -> dict:
    """
    Fase 3 & 4: Pipeline conservativa con scoring spiegabile.
    """
    # 1. Normalizzazione testo e attributi
    norm_desc = normalize_text(raw_description)
    line_attrs = extract_candidate_attributes(raw_description)
    
    # 2. Carica tutti i prodotti attivi
    stmt_products = select(Product).where(Product.is_active == True)
    products = (await db.execute(stmt_products)).scalars().all()
    
    # 3. Carica gli alias esistenti di questo fornitore
    stmt_aliases = select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == fornitore_id)
    aliases_res = (await db.execute(stmt_aliases)).scalars().all()
    
    aliases_by_code = {a.supplier_code: a for a in aliases_res if a.supplier_code and a.status == "approved"}
    aliases_by_desc = {a.normalized_description: a for a in aliases_res if a.status == "approved"}
    
    candidates = []
    
    for p in products:
        score = 0.0
        reason_dict = {
            "supplier_code_match": False,
            "ean_match": False,
            "alias_match": False,
            "brand_match": False,
            "category_match": False,
            "volume_match": False,
            "weight_match": False,
            "variant_match": False,
            "container_match": False,
            "pack_match": False,
            "fuzzy_score": 0,
            "decision": "parking"
        }
        block_flag = False
        matched_alias_id = None
        is_alias_matched = False
        
        # A. Codice fornitore uguale (approved)
        alias_by_code = aliases_by_code.get(supplier_code) if supplier_code else None
        if alias_by_code and alias_by_code.product_id == p.id:
            score = 100.0
            reason_dict["supplier_code_match"] = True
            reason_dict["alias_match"] = True
            matched_alias_id = alias_by_code.id
            is_alias_matched = True
            
        # B. Descrizione normalizzata alias già nota (approved)
        if not is_alias_matched:
            alias_by_desc = aliases_by_desc.get(norm_desc)
            if alias_by_desc and alias_by_desc.product_id == p.id:
                score = 98.0
                reason_dict["alias_match"] = True
                matched_alias_id = alias_by_desc.id
                is_alias_matched = True
            
        # C. EAN uguale (approved)
        if not is_alias_matched and ean:
            has_ean_match = any(a.ean == ean and a.status == "approved" for a in aliases_res if a.product_id == p.id)
            if has_ean_match:
                score = 100.0
                reason_dict["ean_match"] = True
                is_alias_matched = True
                
        # D. Attributi (bonus e blocchi) - Applicati solo se non c'è match diretto tramite alias/EAN
        if not is_alias_matched:
            # Similarità nome: max 45 punti
            fuzzy_score = int(SequenceMatcher(None, norm_desc, normalize_text(p.canonical_name)).ratio() * 100)
            reason_dict["fuzzy_score"] = fuzzy_score
            score += (fuzzy_score / 100.0) * 45

            # Brand
            if p.brand:
                if p.brand.lower() in norm_desc:
                    score += 10
                    reason_dict["brand_match"] = True
                else:
                    block_flag = True
            
            # Category
            from app.services.normalization import infer_category
            line_cat = line_attrs.get("category") or infer_category(raw_description)
            if p.category:
                if line_cat:
                    if line_cat == p.category:
                        score += 15
                        reason_dict["category_match"] = True
                    else:
                        block_flag = True
                else:
                    block_flag = True
                
            # Volume
            line_vol = line_attrs.get("volume_ml")
            if p.volume_ml is not None:
                if line_vol == p.volume_ml:
                    score += 15
                    reason_dict["volume_match"] = True
                elif line_vol is not None:
                    block_flag = True
                
            # Weight
            line_w = line_attrs.get("weight_g")
            if p.weight_g is not None:
                if line_w == p.weight_g:
                    score += 15
                    reason_dict["weight_match"] = True
                elif line_w is not None:
                    block_flag = True
                
            # Pack
            line_pk = line_attrs.get("pack_qty") or 1
            prod_pk = p.unit_count or 1
            if line_pk == prod_pk:
                score += 10
                reason_dict["pack_match"] = True
            else:
                if p.comparison_unit in ("box", "cartone", "cassa"):
                    block_flag = True
                    
            # Container
            line_cont = line_attrs.get("container_type")
            if p.container_type and line_cont:
                if line_cont == p.container_type:
                    score += 5
                    reason_dict["container_match"] = True
                else:
                    block_flag = True
                
        # Determina la decisione
        if is_alias_matched:
            candidate_decision = "auto_match"
        else:
            if score >= 90 and not block_flag:
                candidate_decision = "auto_match"
            elif score >= 70 and not block_flag:
                candidate_decision = "needs_review"
            else:
                candidate_decision = "parking"
            
        reason_dict["decision"] = candidate_decision
        
        candidates.append({
            "product_id": p.id,
            "sku_interno": p.sku_interno,
            "canonical_name": p.canonical_name,
            "score": score,
            "decision": candidate_decision,
            "block": block_flag,
            "reason_json": reason_dict,
            "supplier_alias_id": matched_alias_id,
        })
        
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    if candidates:
        best = candidates[0]
        best_decision = "parking" if best["score"] < 70 or (best["score"] < 90 and best["decision"] == "auto_match" and not best["supplier_alias_id"]) else best["decision"]
        return {
            "product_id": best["product_id"] if best_decision != "parking" else None,
            "sku_interno": best["sku_interno"] if best_decision != "parking" else None,
            "canonical_name": best["canonical_name"] if best_decision != "parking" else None,
            "supplier_alias_id": best["supplier_alias_id"] if best_decision != "parking" else None,
            "score": best["score"],
            "decision": best_decision,
            "reason": json.dumps(best["reason_json"]),
            "candidates": candidates[:5],
        }
        
    return {
        "product_id": None,
        "sku_interno": None,
        "canonical_name": None,
        "supplier_alias_id": None,
        "score": 0.0,
        "decision": "parking",
        "reason": json.dumps({"note": "Nessun prodotto nel catalogo canonico"}),
        "candidates": [],
    }


async def match_riga(
    db: AsyncSession,
    fornitore_id: int,
    codice_articolo: str | None,
    tipo_codice: str | None,
    descrizione: str,
    prezzo_netto_normalizzato: Decimal,
    quantita: Decimal,
    unita_misura_fattura: str | None,
    data_documento: str,
) -> MatchResult:
    """
    Wrapper retrocompatibile che adotta la v2 Pipeline.
    """
    result = MatchResult()
    result.prezzo_fatturato_normalizzato = prezzo_netto_normalizzato
    
    ean = codice_articolo if (tipo_codice and tipo_codice.upper() in ("EAN", "EAN13", "EAN8", "GTIN")) else None
    
    res_v2 = await resolve_invoice_line_product(
        db=db,
        fornitore_id=fornitore_id,
        raw_description=descrizione,
        supplier_code=codice_articolo,
        ean=ean,
    )
    
    result.product_id = res_v2["product_id"]
    result.supplier_alias_id = res_v2["supplier_alias_id"]
    result.score = res_v2["score"]
    result.decision = res_v2["decision"]
    result.reason = res_v2["reason"]
    result.candidates = res_v2["candidates"]
    
    if result.decision == "auto_match" and res_v2["sku_interno"]:
        listino = await _get_listino_attivo(db, fornitore_id, res_v2["sku_interno"], data_documento)
        if listino:
            result.matched = True
            result.livello = 1
            result.sku_interno = res_v2["sku_interno"]
            result.listino_id = listino.id
            result.prezzo_listino = listino.prezzo_pattuito
            
            # Applica normalizzazione del prezzo
            product_obj = await db.get(Product, result.product_id)
            
            class TempInvoiceLine:
                def __init__(self, desc, price, qty, uom):
                    self.descrizione_fornitore_raw = desc
                    self.prezzo_unitario_fatturato = price
                    self.sconto_percentuale = Decimal("0")
                    self.quantita = qty
                    self.unita_misura_fattura = uom
                    
            line_obj = TempInvoiceLine(descrizione, prezzo_netto_normalizzato, quantita, unita_misura_fattura)
            norm_price_res = normalize_price_for_comparison(line_obj, product_obj)
            
            if norm_price_res.reliable:
                result.prezzo_fatturato_normalizzato = norm_price_res.normalized_unit_price
                result.delta_prezzo = (result.prezzo_fatturato_normalizzato - listino.prezzo_pattuito).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                result.delta_totale = (result.delta_prezzo * quantita).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
            else:
                result.matched = False
                result.livello = 4
            return result
            
    if result.decision == "needs_review" and res_v2["sku_interno"]:
        result.livello = 3
        result.suggerimento_sku = res_v2["sku_interno"]
        result.suggerimento_desc = res_v2["canonical_name"]
    else:
        result.livello = 4
        
    result.matched = False
    return result


async def _get_listino_attivo(
    db: AsyncSession, fornitore_id: int, sku_interno: str, data_documento: str
) -> Optional[ListinoMaster]:
    """
    Trova il record ListinoMaster attivo alla data del documento.
    """
    from datetime import date as date_type
    if isinstance(data_documento, str):
        try:
            doc_date = date_type.fromisoformat(data_documento)
        except ValueError:
            doc_date = date_type.today()
    else:
        doc_date = data_documento

    result = await db.execute(
        select(ListinoMaster)
        .where(
            and_(
                ListinoMaster.fornitore_id == fornitore_id,
                ListinoMaster.sku_interno == sku_interno,
                ListinoMaster.data_inizio_validita <= doc_date,
            )
        )
        .where(
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= doc_date)
        )
        .order_by(ListinoMaster.data_inizio_validita.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
