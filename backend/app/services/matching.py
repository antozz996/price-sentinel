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
    pack_qty: int
    reliable: bool = True


def normalize_price_for_comparison(invoice_line, product: Product) -> NormalizedPriceResult:
    """
    Fase 5: Normalizzazione del prezzo unitario per il confronto.
    """
    raw_unit_price = Decimal(str(getattr(invoice_line, "prezzo_unitario_fatturato", 0) or 0))
    discount = Decimal(str(getattr(invoice_line, "sconto_percentuale", 0) or 0))
    
    # Calcolo prezzo netto unitario
    net_price = raw_unit_price * (Decimal("1") - discount / Decimal("100"))
    
    comp_unit = product.comparison_unit
    unit_count = product.unit_count or 1
    
    descrizione = getattr(invoice_line, "descrizione_fornitore_raw", "") or ""
    line_pack = extract_pack_qty(descrizione)
    pack_qty = line_pack if line_pack is not None else unit_count
    
    reliable = True
    
    # 1. Se il prezzo è a bottiglia/pezzo, e abbiamo acquistato un pack,
    # dividiamo il prezzo per il numero di pezzi per confezione.
    if comp_unit in ("bottle", "piece"):
        if pack_qty > 1:
            net_price = net_price / Decimal(str(pack_qty))
            
    # 2. Se l'unità è liter, calcoliamo il prezzo a litro.
    elif comp_unit == "liter":
        vol_ml = product.volume_ml or extract_volume_ml(descrizione)
        if vol_ml:
            uom_fattura = str(getattr(invoice_line, "unita_misura_fattura", "") or "").lower()
            is_package_uom = any(x in uom_fattura for x in ("cassa", "cartone", "box", "conf", "crt", "css"))
            if is_package_uom and pack_qty > 1:
                prezzo_singolo = net_price / Decimal(str(pack_qty))
            else:
                prezzo_singolo = net_price
            net_price = prezzo_singolo / (Decimal(str(vol_ml)) / Decimal("1000"))
        else:
            reliable = False
            
    # 3. Se l'unità è kg, calcoliamo il prezzo al kg.
    elif comp_unit == "kg":
        weight_g = product.weight_g or extract_weight_g(descrizione)
        if weight_g:
            uom_fattura = str(getattr(invoice_line, "unita_misura_fattura", "") or "").lower()
            is_package_uom = any(x in uom_fattura for x in ("cassa", "cartone", "box", "conf", "crt", "css"))
            if is_package_uom and pack_qty > 1:
                prezzo_singolo = net_price / Decimal(str(pack_qty))
            else:
                prezzo_singolo = net_price
            net_price = prezzo_singolo / (Decimal(str(weight_g)) / Decimal("1000"))
        else:
            reliable = False
            
    # 4. Se l'unità è box/cassa, e il prezzo è al singolo pezzo
    elif comp_unit == "box":
        uom_fattura = str(getattr(invoice_line, "unita_misura_fattura", "") or "").lower()
        is_package_uom = any(x in uom_fattura for x in ("cassa", "cartone", "box", "conf", "crt", "css"))
        if not is_package_uom and pack_qty > 1:
            net_price = net_price * Decimal(str(unit_count))
            
    return NormalizedPriceResult(
        normalized_unit_price=net_price,
        comparison_unit=comp_unit,
        pack_qty=pack_qty,
        reliable=reliable,
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
    
    aliases_by_code = {a.supplier_code: a for a in aliases_res if a.supplier_code}
    aliases_by_desc = {a.normalized_description: a for a in aliases_res}
    
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
        
        # A. Codice fornitore uguale
        alias_by_code = aliases_by_code.get(supplier_code) if supplier_code else None
        if alias_by_code and alias_by_code.product_id == p.id:
            score += 100
            reason_dict["supplier_code_match"] = True
            reason_dict["alias_match"] = True
            matched_alias_id = alias_by_code.id
            
        # B. Descrizione normalizzata alias già nota
        alias_by_desc = aliases_by_desc.get(norm_desc)
        if alias_by_desc and alias_by_desc.product_id == p.id:
            score += 95
            reason_dict["alias_match"] = True
            matched_alias_id = alias_by_desc.id
            
        # C. EAN uguale
        if ean:
            has_ean_match = any(a.ean == ean for a in aliases_res if a.product_id == p.id)
            if has_ean_match:
                score += 100
                reason_dict["ean_match"] = True
                
        is_alias_matched = reason_dict["alias_match"] or reason_dict["ean_match"]

        # D. Attributi (bonus e blocchi) - Applicati solo se non c'è match diretto tramite alias/EAN
        if not is_alias_matched:
            # Brand
            if p.brand:
                if p.brand in norm_desc:
                    score += 25
                    reason_dict["brand_match"] = True
                else:
                    score -= 30
                    block_flag = True
            else:
                score += 10
                
            # Category
            if p.category:
                line_cat = line_attrs["category"]
                if line_cat:
                    if line_cat == p.category:
                        score += 15
                        reason_dict["category_match"] = True
                    else:
                        block_flag = True
                else:
                    if p.category == "beverage" and any(x in norm_desc for x in ["acqua", "cola", "soda", "tonica", "aranciata", "succo", "gin", "vodka", "rum", "amaro", "birra", "vino"]):
                        score += 15
                        reason_dict["category_match"] = True
                    else:
                        score += 5
            else:
                score += 10
                
            # Volume
            line_vol = line_attrs["volume_ml"]
            if p.volume_ml is not None:
                if line_vol == p.volume_ml:
                    score += 25
                    reason_dict["volume_match"] = True
                elif line_vol is not None:
                    block_flag = True
            elif line_vol is None:
                score += 10
                
            # Weight
            line_w = line_attrs["weight_g"]
            if p.weight_g is not None:
                if line_w == p.weight_g:
                    score += 20
                    reason_dict["weight_match"] = True
                elif line_w is not None:
                    block_flag = True
            elif line_w is None:
                score += 10
                
            # Variant / Gusto
            # Tratta "classica" e None come equivalenti
            if p.variant and p.variant != "classica":
                if p.variant in norm_desc:
                    score += 20
                    reason_dict["variant_match"] = True
                else:
                    block_flag = True
            else:
                known_variants = ["fragola", "pesca", "sugarfree", "zero"]
                if any(v in norm_desc for v in known_variants):
                    block_flag = True
                else:
                    score += 20
                    reason_dict["variant_match"] = True
                
            # Container
            line_cont = line_attrs["container_type"]
            if p.container_type and line_cont:
                if line_cont == p.container_type:
                    score += 10
                    reason_dict["container_match"] = True
                else:
                    block_flag = True
            elif not line_cont:
                score += 5
                
            # Pack
            line_pk = line_attrs["pack_qty"] or 1
            prod_pk = p.unit_count or 1
            if line_pk == prod_pk:
                score += 10
                reason_dict["pack_match"] = True
            else:
                if p.comparison_unit in ("box", "cartone", "cassa"):
                    block_flag = True
                    
            # Fuzzy score
            fuzzy_score = int(SequenceMatcher(None, norm_desc, normalize_text(p.canonical_name)).ratio() * 100)
            reason_dict["fuzzy_score"] = fuzzy_score
            if fuzzy_score > 85:
                score += 15
            elif fuzzy_score >= 70:
                score += 8
                
        # Determina la decisione
        if score >= 90 and not block_flag:
            candidate_decision = "auto_match"
        elif score >= 70 or (score >= 90 and block_flag):
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
        best_decision = "parking" if best["score"] < 70 else best["decision"]
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
