import asyncio
import argparse
import json
import os
import sys
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import import_supplier_list_excel
from app.services.matching import resolve_invoice_line_product

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)

async def run_safe_import(mode: str):
    supplier_id = 11  # Navas Srl
    filepath = "data/import_samples/storico_prezzi_navas.xlsx"
    
    if not os.path.exists(filepath):
        print(f"Errore: Il file {filepath} non esiste.")
        sys.exit(1)
        
    with open(filepath, "rb") as f:
        file_bytes = f.read()
        
    async with async_session_factory() as db:
        # 1. Rileva i conteggi prima dell'operazione
        async with db.begin():
            mc_before = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id))).scalar()
            alias_before = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            lm_before = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id))).scalar()
            prod_before = (await db.execute(select(func.count(Product.id)))).scalar()

        # Esegui importazione in modalità dry_run per raccogliere le classificazioni del listino
        async with db.begin():
            res = await import_supplier_list_excel(
                db=db, 
                supplier_id=supplier_id, 
                file_bytes=file_bytes, 
                dry_run=True
            )
            preview = res.get("preview", [])
        
        group_a = [] # safe_auto_import
        group_b = [] # manual_review_good_candidate
        group_c = [] # manual_review_no_candidate
        group_d = [] # rejected_candidate_brand_mismatch
        group_s = [] # manual_review_pack_suspect (3 sospetti pack)
        
        for p in preview:
            score = p.get("score", 0.0)
            decision = p.get("decision")
            raw_desc = p.get("raw_description")
            supplier_code = p.get("supplier_code")
            price = p.get("price", 0.0)
            pack_qty = p.get("pack_qty", 1)
            volume_ml = p.get("volume_ml")
            category = p.get("category")
            warning = p.get("warning") or ""
            uom = p.get("uom", "piece")
            normalized_description = p.get("normalized_description")
            
            is_blocked = "Matching bloccato" in warning
            
            item_data = {
                "raw_description": raw_desc,
                "normalized_description": normalized_description,
                "supplier_code": supplier_code,
                "price": price,
                "uom": uom,
                "pack_qty": pack_qty,
                "volume_ml": volume_ml,
                "category": category,
                "score": score,
                "warning": warning if warning else None
            }
            
            # Gruppo D: Mismatch Brand/Categoria/Volume (bloccato)
            if is_blocked:
                item_data["candidate_sku"] = None
                group_d.append(item_data)
                
            # Gruppo A: Auto Match (Verifica prezzi e pack)
            elif decision == "auto_match":
                matched_sku = p.get("matched_sku")
                item_data["matched_sku"] = matched_sku
                
                # Se pack_qty=1 ma prezzo > 1.0 per acqua/soft drink -> declassa a manual_review_pack_suspect
                is_suspect_pack = False
                if pack_qty == 1 and price > 1.0 and category in ("acqua", "soft_drink"):
                    is_suspect_pack = True
                
                if is_suspect_pack:
                    item_data["warning"] = "SOSPETTO CARTONE: " + (item_data["warning"] or "Prezzo elevato per singola unità")
                    group_s.append(item_data)
                else:
                    group_a.append(item_data)
                    
            # Gruppo B: Parking con buon candidato (score >= 70 e non bloccato)
            elif decision == "parking" and score >= 70.0:
                # Trova candidate SKU
                async with db.begin():
                    res_match = await resolve_invoice_line_product(
                        db=db,
                        fornitore_id=supplier_id,
                        raw_description=raw_desc,
                        supplier_code=supplier_code
                    )
                best_candidate = res_match["candidates"][0] if res_match.get("candidates") else {}
                candidate_sku = best_candidate.get("sku_interno")
                
                item_data["candidate_sku"] = candidate_sku
                group_b.append(item_data)
                
            # Gruppo C: Sotto 70 o riga sporca
            else:
                item_data["candidate_sku"] = None
                group_c.append(item_data)
                
        # Scrivi report JSON
        report = {
            "summary": {
                "righe_totali": len(preview),
                "safe_auto_import_count": len(group_a),
                "manual_review_good_candidate_count": len(group_b),
                "manual_review_pack_suspect_count": len(group_s),
                "manual_review_no_candidate_count": len(group_c),
                "rejected_candidate_brand_mismatch_count": len(group_d)
            },
            "groups": {
                "safe_auto_import": group_a,
                "manual_review_good_candidate": group_b,
                "manual_review_pack_suspect": group_s,
                "manual_review_no_candidate": group_c,
                "rejected_candidate_brand_mismatch": group_d
            }
        }
        
        output_path = "data/import_samples/safe_import_gate_report.json"
        with open(output_path, "w") as out:
            json.dump(report, out, cls=CustomEncoder, indent=2)
            
        print("\n" + "="*50)
        print("🛡️ REPORT SAFE IMPORT GATE NAVAS")
        print("="*50)
        print(f"Righe totali con prezzo: {report['summary']['righe_totali']}")
        print(f"A. Safe Auto-Import:            {report['summary']['safe_auto_import_count']}")
        print(f"B. Good Candidates (70-89%):    {report['summary']['manual_review_good_candidate_count']}")
        print(f"S. Pack Suspects:               {report['summary']['manual_review_pack_suspect_count']}")
        print(f"C. No Candidates (<70%):        {report['summary']['manual_review_no_candidate_count']}")
        print(f"D. Brand/Attr Mismatches:       {report['summary']['rejected_candidate_brand_mismatch_count']}")
        print("="*50)
        print(f"Report JSON completo salvato in: {output_path}\n")

        # 3. Esegui modifiche a DB (se in apply mode)
        created_count = 0
        if mode == "apply-good-candidates-only":
            print("Esecuzione in modalità APPLY: Inserimento dei 19 candidati a database...")
            async with db.begin():
                for item in group_b:
                    # Idempotenza: cerca se esiste già
                    stmt = select(MatchCandidate).where(
                        MatchCandidate.supplier_id == supplier_id,
                        MatchCandidate.raw_description == item["raw_description"],
                        MatchCandidate.status == "pending"
                    )
                    exists = (await db.execute(stmt)).scalars().first()
                    if exists:
                        continue
                    
                    # Recupera ID del prodotto dal candidate_sku
                    sku = item["candidate_sku"]
                    p_stmt = select(Product.id).where(Product.sku_interno == sku)
                    prod_id = (await db.execute(p_stmt)).scalar()
                    
                    # Crea MatchCandidate
                    new_mc = MatchCandidate(
                        supplier_id=supplier_id,
                        product_id=prod_id,
                        source_type="price_list_row",
                        raw_description=item["raw_description"],
                        normalized_description=item["normalized_description"],
                        score=item["score"],
                        block_flag=False,
                        status="pending",
                        reason_json={
                            "raw_description": item["raw_description"],
                            "supplier_code": item["supplier_code"],
                            "price": item["price"],
                            "uom": item["uom"],
                            "pack_qty": item["pack_qty"],
                            "volume_ml": item["volume_ml"],
                            "score": item["score"],
                            "match_reason": "good_candidate",
                            "warning": item["warning"],
                            "source": "navas_safe_import_gate"
                        }
                    )
                    db.add(new_mc)
                    created_count += 1
            print(f"Inserimento terminato! MatchCandidate creati: {created_count}")

        # 4. Rileva i conteggi dopo l'operazione per verifica
        async with db.begin():
            mc_after = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id))).scalar()
            alias_after = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            lm_after = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id))).scalar()
            prod_after = (await db.execute(select(func.count(Product.id)))).scalar()

        print("\n" + "="*50)
        print("📈 VERIFICA CONTEGGI SUL DATABASE")
        print("="*50)
        print(f"Product:              Prima={prod_before} | Dopo={prod_after} | Diff={prod_after - prod_before}")
        print(f"Alias (Fornitore 11): Prima={alias_before} | Dopo={alias_after} | Diff={alias_after - alias_before}")
        print(f"Listino (Fornitore 11): Prima={lm_before} | Dopo={lm_after} | Diff={lm_after - lm_before}")
        print(f"Candidati (Fornitore 11): Prima={mc_before} | Dopo={mc_after} | Diff={mc_after - mc_before}")
        print("="*50 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Navas Safe Import Gate Script")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Esegui classificazione senza modificare il DB")
    group.add_argument("--apply-good-candidates-only", action="store_true", help="Crea solo i 19 MatchCandidate a DB")
    args = parser.parse_args()
    
    mode_str = "dry-run"
    if args.apply_good_candidates_only:
        mode_str = "apply-good-candidates-only"
        
    asyncio.run(run_safe_import(mode_str))
