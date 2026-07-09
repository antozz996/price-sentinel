import asyncio
import json
import os
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product
from app.services.supplier_list_import import import_supplier_list_excel
from app.services.matching import resolve_invoice_line_product

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)

async def generate():
    supplier_id = 11  # Navas Srl
    filepath = "data/import_samples/storico_prezzi_navas.xlsx"
    
    with open(filepath, "rb") as f:
        file_bytes = f.read()
        
    async with async_session_factory() as db:
        res = await import_supplier_list_excel(
            db=db, 
            supplier_id=supplier_id, 
            file_bytes=file_bytes, 
            dry_run=True
        )
        
        preview = res.get("preview", [])
        errori_parsing = res.get("errori_parsing", [])
        
        # 1. Riepilogo
        righe_totali = res["righe_totali_lette"]
        righe_con_prezzo = len(preview)
        righe_scartate = res["righe_scartate"]
        
        auto_matches = []
        parking_70_89 = []
        under_70 = []
        
        for p in preview:
            score = p.get("score", 0.0)
            decision = p.get("decision")
            raw_desc = p.get("raw_description")
            supplier_code = p.get("supplier_code")
            price = p.get("price")
            pack_qty = p.get("pack_qty")
            warning = p.get("warning")
            category = p.get("category")
            
            if decision == "auto_match":
                auto_matches.append({
                    "raw_description": raw_desc,
                    "supplier_code": supplier_code,
                    "matched_sku": p.get("matched_sku"),
                    "score": score,
                    "match_reason": p.get("match_reason"),
                    "price": price,
                    "pack_qty": pack_qty,
                    "warning": warning
                })
            elif decision == "parking" and score >= 70.0:
                # Trova candidate_sku e motivazione con resolve_invoice_line_product
                res_match = await resolve_invoice_line_product(
                    db=db,
                    fornitore_id=supplier_id,
                    raw_description=raw_desc,
                    supplier_code=supplier_code
                )
                best_candidate = res_match["candidates"][0] if res_match.get("candidates") else {}
                candidate_sku = best_candidate.get("sku_interno")
                reason = best_candidate.get("reason", "Fuzzy text match")
                
                parking_70_89.append({
                    "raw_description": raw_desc,
                    "supplier_code": supplier_code,
                    "candidate_sku": candidate_sku,
                    "score": score,
                    "reason": reason,
                    "price": price,
                    "pack_qty": pack_qty,
                    "warning": warning
                })
            else:
                # Sotto 70
                # Tenta comunque di trovare se c'è un candidato migliore o perché ha fallito
                res_match = await resolve_invoice_line_product(
                    db=db,
                    fornitore_id=supplier_id,
                    raw_description=raw_desc,
                    supplier_code=supplier_code
                )
                best_candidate = res_match["candidates"][0] if res_match.get("candidates") else {}
                candidate_sku = best_candidate.get("sku_interno")
                score_match = best_candidate.get("score", 0.0) if best_candidate else 0.0
                
                under_70.append({
                    "raw_description": raw_desc,
                    "supplier_code": supplier_code,
                    "score": score,
                    "category": category,
                    "candidate_sku": candidate_sku,
                    "best_score_found": score_match,
                    "warning": warning
                })
                
        # Scrivi report di dettaglio
        report = {
            "riepilogo": {
                "righe_totali": righe_totali,
                "righe_con_prezzo_valido": righe_con_prezzo,
                "righe_scartate": righe_scartate,
                "auto_match_previsti": len(auto_matches),
                "parking_70_89": len(parking_70_89),
                "parking_under_70": len(under_70),
                "errori_parsing": len(errori_parsing),
                "errori_parsing_dettaglio": errori_parsing
            },
            "auto_matches": auto_matches,
            "parking_70_89": parking_70_89,
            "under_70": under_70
        }
        
        output_path = "data/import_samples/detailed_dry_run_report.json"
        with open(output_path, "w") as out:
            json.dump(report, out, cls=CustomEncoder, indent=2)
            
        print(f"Report dettagliato salvato con successo in {output_path}")

if __name__ == "__main__":
    asyncio.run(generate())
