import openpyxl
from io import BytesIO
from decimal import Decimal
from datetime import date
import math
import re
from typing import Optional, List, Dict, Any

from sqlalchemy import select, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.normalization import normalize_text, extract_volume_ml, infer_category
from app.services.matching import resolve_invoice_line_product


def clean_price(val) -> Optional[Decimal]:
    """
    Pulisce e converte i prezzi espressi in stringa o numero.
    Gestisce la virgola decimale italiana, il simbolo €, gli spazi e i testi non numerici.
    """
    if val is None:
        return None
    s = str(val).strip().replace(" ", "").replace("€", "")
    if s.upper() in ("VEDALL", "VEDIALLEGATO", "N.D.", "-", "", "ND", "N/D"):
        return None
    
    # Gestione separatori decimali e delle migliaia italiani
    if "," in s and "." in s:
        if s.index(".") < s.index(","):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "").replace(".", ".")
    elif "," in s:
        s = s.replace(",", ".")
        
    try:
        return Decimal(s)
    except Exception:
        return None


def clean_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        # Rimuove eventuali decimali tipo .0
        f = float(val)
        if not math.isnan(f):
            return int(f)
    except Exception:
        pass
    return None


def map_excel_columns(headers: List) -> Dict[str, int]:
    """
    Trova l'indice delle colonne in base a sinonimi predefiniti.
    """
    mapping = {}
    normalized_headers = [str(h).strip().lower() for h in headers if h is not None]
    
    synonyms = {
        "raw_description": ["prodotto", "descrizione", "articolo", "nome articolo", "nome", "descrizione articolo"],
        "supplier_code": ["codice articolo", "codice", "sku fornitore", "codice art.", "sku", "cod. art.", "cod.articolo", "cod.art"],
        "price": ["prezzo netto", "prezzo", "listino", "costo", "prezzo pattuito", "prezzo unitario"],
        "uom": ["unità misura", "um", "u.m.", "unita misura", "unita di misura"],
        "pack_qty": ["confezione", "pack", "pz x conf", "pezzi", "formato", "quantità conf.", "quantita conf", "quantità", "quantita", "pz/conf"]
    }
    
    for key, syns in synonyms.items():
        for syn in syns:
            for idx, h in enumerate(normalized_headers):
                if syn == h or h.startswith(syn) or syn in h:
                    mapping[key] = idx
                    break
            if key in mapping:
                break
    return mapping


async def save_append_only_price(
    db: AsyncSession,
    fornitore_id: int,
    sku_interno: str,
    descrizione: str,
    prezzo_pattuito: Decimal,
    unita_misura: str,
    data_inizio: date
) -> str:
    """
    Salva il prezzo concordato in modo append-only.
    - Se prezzo e uom sono uguali all'attivo: unchanged.
    - Se diversi: scade il vecchio e ne crea uno nuovo (updated).
    - Se inesistente: crea il primo record (created).
    """
    stmt = select(ListinoMaster).where(
        and_(
            ListinoMaster.fornitore_id == fornitore_id,
            ListinoMaster.sku_interno == sku_interno,
            ListinoMaster.data_scadenza.is_(None)
        )
    )
    res = await db.execute(stmt)
    attivi = res.scalars().all()
    
    if attivi:
        corrente = attivi[0]
        if corrente.prezzo_pattuito == prezzo_pattuito and corrente.unita_misura == unita_misura:
            return "unchanged"
        else:
            corrente.data_scadenza = data_inizio
            db.add(corrente)
            
            nuovo = ListinoMaster(
                fornitore_id=fornitore_id,
                sku_interno=sku_interno,
                descrizione=descrizione,
                prezzo_pattuito=prezzo_pattuito,
                unita_misura=unita_misura,
                data_inizio_validita=data_inizio,
                data_scadenza=None
            )
            db.add(nuovo)
            return "updated"
    else:
        nuovo = ListinoMaster(
            fornitore_id=fornitore_id,
            sku_interno=sku_interno,
            descrizione=descrizione,
            prezzo_pattuito=prezzo_pattuito,
            unita_misura=unita_misura,
            data_inizio_validita=data_inizio,
            data_scadenza=None
        )
        db.add(nuovo)
        return "created"


async def import_supplier_list_excel(
    db: AsyncSession,
    supplier_id: int,
    file_bytes: bytes,
    data_validita: Optional[date] = None
) -> dict:
    if not data_validita:
        data_validita = date.today()

    try:
        wb = openpyxl.load_workbook(filename=BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as e:
        return {"error": f"Impossibile leggere il file Excel: {str(e)}"}

    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {"error": "Il file Excel è vuoto."}

    # 1. Rilevamento riga di intestazione (header)
    header_idx = -1
    best_mapping = {}
    
    # Scansiona le prime 15 righe per trovare quella con più corrispondenze
    for i in range(min(15, len(rows))):
        row_vals = rows[i]
        m = map_excel_columns(row_vals)
        if len(m) > len(best_mapping):
            best_mapping = m
            header_idx = i

    if "raw_description" not in best_mapping or "price" not in best_mapping:
        return {
            "error": "Impossibile rilevare le colonne obbligatorie (Prezzo e Descrizione) nel foglio Excel."
        }

    # Estrai intestazioni e righe dati
    headers = [str(x) if x is not None else "" for x in rows[header_idx]]
    data_rows = rows[header_idx + 1:]

    # Statistiche di importazione
    totale_lette = len(data_rows)
    righe_importate = 0
    alias_approvati_creati = 0
    alias_esistenti_riconosciuti = 0
    prezzi_nuovi_creati = 0
    prezzi_invariati = 0
    prezzi_storicizzati = 0
    candidati_creati = 0
    righe_scartate = 0
    errori_parsing = []
    preview = []

    # Indici colonne
    desc_idx = best_mapping["raw_description"]
    price_idx = best_mapping["price"]
    code_idx = best_mapping.get("supplier_code")
    uom_idx = best_mapping.get("uom")
    pack_idx = best_mapping.get("pack_qty")

    for idx, row in enumerate(data_rows):
        # Ignora righe completamente vuote
        if not any(cell is not None for cell in row):
            totale_lette -= 1
            continue

        raw_desc = str(row[desc_idx]).strip() if row[desc_idx] is not None else ""
        if not raw_desc:
            righe_scartate += 1
            errori_parsing.append(f"Riga {idx + header_idx + 2}: Descrizione vuota.")
            continue

        price_raw = row[price_idx]
        price_val = clean_price(price_raw)
        if price_val is None:
            righe_scartate += 1
            errori_parsing.append(f"Riga {idx + header_idx + 2}: Prezzo non valido o vuoto ('{price_raw}').")
            continue

        # Estrai altri attributi
        supplier_code = str(row[code_idx]).strip() if code_idx is not None and row[code_idx] is not None else None
        uom_raw = str(row[uom_idx]).strip() if uom_idx is not None and row[uom_idx] is not None else "piece"
        pack_raw = row[pack_idx] if pack_idx is not None else None
        pack_qty = clean_int(pack_raw)

        # Normalizzazioni descrizioni ed estrazioni fisiche
        normalized_description = normalize_text(raw_desc)
        volume_ml = extract_volume_ml(raw_desc)
        weight_g = None  # Estrazione peso g se presente
        category = infer_category(raw_desc)
        container_type = None

        # Se pack_qty non è specificato in colonna, prova ad estrarlo
        if not pack_qty:
            if "x" in normalized_description:
                m_conf = re.search(r'x\s*(\d+)', normalized_description)
                if m_conf:
                    pack_qty = int(m_conf.group(1))
            if not pack_qty:
                pack_qty = 1

        # UOM standard
        uom = "piece"
        uom_lower = uom_raw.lower()
        if uom_lower in ("lt", "litri", "litro", "l"):
            uom = "liter"
        elif uom_lower in ("kg", "chilo", "kilo"):
            uom = "kg"
        elif uom_lower in ("bottiglia", "bot", "bt"):
            uom = "bottle"
        elif uom_lower in ("scatola", "cassa", "box", "conf", "confezione"):
            uom = "box"

        # 4. MATCHING AUTOMATICO
        # A. Verifica se esiste già un alias approvato per lo stesso fornitore e descrizione
        alias_stmt = select(SupplierProductAlias).options(
            selectinload(SupplierProductAlias.product)
        ).where(
            and_(
                SupplierProductAlias.supplier_id == supplier_id,
                or_(
                    SupplierProductAlias.raw_description == raw_desc,
                    and_(SupplierProductAlias.supplier_code == supplier_code, SupplierProductAlias.supplier_code.isnot(None))
                )
            )
        )
        alias_res = await db.execute(alias_stmt)
        alias = alias_res.scalar_one_or_none()

        match_status = "parking"
        matched_sku = None
        score = 0.0

        if alias and alias.status == "approved":
            # Alias esistente approvato -> match sicuro!
            match_status = "auto_match"
            matched_sku = alias.product.sku_interno
            alias_esistenti_riconosciuti += 1
            
            # Aggiorna attributi pack/volume se vuoti
            if alias.pack_qty is None:
                alias.pack_qty = pack_qty
            if alias.volume_ml is None:
                alias.volume_ml = volume_ml
            db.add(alias)
        else:
            # Esegui motore di matching
            res_match = await resolve_invoice_line_product(
                db=db,
                fornitore_id=supplier_id,
                raw_description=raw_desc,
                supplier_code=supplier_code
            )
            
            best_candidate = res_match["candidates"][0] if res_match.get("candidates") else None
            if best_candidate:
                score = best_candidate["score"]
                block_flag = best_candidate["block"]
                best_product_id = best_candidate["product_id"]
                best_sku = best_candidate["sku_interno"]
            else:
                score = 0.0
                block_flag = False
                best_product_id = None
                best_sku = None

            if score >= 90.0 and not block_flag and best_product_id:
                # Match sicuro! Crea alias approvato
                match_status = "auto_match"
                matched_sku = best_sku
                
                alias = SupplierProductAlias(
                    supplier_id=supplier_id,
                    product_id=best_product_id,
                    supplier_code=supplier_code,
                    raw_description=raw_desc,
                    normalized_description=normalized_description,
                    pack_qty=pack_qty,
                    volume_ml=volume_ml,
                    weight_g=weight_g,
                    container_type=container_type,
                    status="approved",
                    source="import",
                    confidence_score=score
                )
                db.add(alias)
                alias_approvati_creati += 1
            else:
                # Match dubbio -> crea MatchCandidate in Parking Area
                match_status = "parking"
                
                # Idempotenza: cerca se esiste già un candidato identico pending
                cand_stmt = select(MatchCandidate).where(
                    and_(
                        MatchCandidate.supplier_id == supplier_id,
                        MatchCandidate.raw_description == raw_desc,
                        MatchCandidate.status == "pending"
                    )
                )
                cand_res = await db.execute(cand_stmt)
                candidate_exist = cand_res.scalars().first()
                
                if not candidate_exist:
                    # Se lo score è < 70, il product_id è Null (senza aggancio certo)
                    linked_prod_id = best_product_id if score >= 70.0 else None
                    
                    candidate = MatchCandidate(
                        supplier_id=supplier_id,
                        product_id=linked_prod_id,
                        source_type="price_list_row",
                        raw_description=raw_desc,
                        normalized_description=normalized_description,
                        score=score,
                        block_flag=block_flag,
                        status="pending",
                        reason_json={
                            "price": float(price_val),
                            "uom": uom,
                            "pack_qty": pack_qty,
                            "volume_ml": volume_ml,
                            "category": category
                        }
                    )
                    db.add(candidate)
                    candidati_creati += 1

        # 5. SALVATAGGIO PREZZI (Solo se match_status == "auto_match")
        price_outcome = None
        if match_status == "auto_match" and matched_sku:
            outcome = await save_append_only_price(
                db=db,
                fornitore_id=supplier_id,
                sku_interno=matched_sku,
                descrizione=raw_desc,
                prezzo_pattuito=price_val,
                unita_misura=uom,
                data_inizio=data_validita
            )
            price_outcome = outcome
            if outcome == "created":
                prezzi_nuovi_creati += 1
            elif outcome == "updated":
                prezzi_storicizzati += 1
                prezzi_nuovi_creati += 1
            elif outcome == "unchanged":
                prezzi_invariati += 1
            righe_importate += 1

        # Genera preview dei primi 20 risultati
        if len(preview) < 20:
            preview.append({
                "row_index": idx + header_idx + 2,
                "raw_description": raw_desc,
                "supplier_code": supplier_code,
                "price": float(price_val),
                "uom": uom,
                "pack_qty": pack_qty,
                "match_status": match_status,
                "matched_sku": matched_sku,
                "score": score,
                "price_outcome": price_outcome
            })

    await db.flush()

    return {
        "righe_totali_lette": totale_lette,
        "righe_importate": righe_importate,
        "alias_approvati_creati": alias_approvati_creati,
        "alias_gia_esistenti_riconosciuti": alias_esistenti_riconosciuti,
        "prezzi_nuovi_creati": prezzi_nuovi_creati,
        "prezzi_invariati": prezzi_invariati,
        "prezzi_storicizzati": prezzi_storicizzati,
        "match_candidates_creati": candidati_creati,
        "righe_scartate": righe_scartate,
        "errori_parsing": errori_parsing[:50],
        "preview": preview
    }
