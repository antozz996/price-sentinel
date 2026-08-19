import asyncio
from decimal import Decimal
from difflib import SequenceMatcher
from sqlalchemy import select
from app.database import async_session_factory
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.services.normalization import normalize_text, extract_candidate_attributes, infer_category

async def main():
    async with async_session_factory() as db:
        products = (await db.scalars(select(Product).where(Product.is_active == True))).all()
        prod_data = []
        for p in products:
            prod_data.append({
                "id": p.id,
                "sku": p.sku_interno,
                "name": p.canonical_name,
                "norm_name": normalize_text(p.canonical_name),
                "brand": (p.brand or "").lower(),
                "category": p.category,
                "vol": p.volume_ml,
            })
        print(f"Loaded {len(prod_data)} canonical products.")

        lines = (await db.scalars(select(RigaFattura).join(Fattura))).all()
        print(f"Processing {len(lines)} lines in DB...")
        
        candidates_to_add = []
        for riga in lines:
            if not riga.descrizione_fornitore_raw:
                continue
            desc = riga.descrizione_fornitore_raw.strip()
            if desc.startswith("Dest.") or desc.startswith("Rif.") or desc == "." or len(desc) < 3:
                continue
            
            inv = await db.get(Fattura, riga.fattura_id)
            if not inv:
                continue
            
            riga.stato_matching = StatoMatching.in_parking
            norm_desc = normalize_text(desc)
            line_cat = infer_category(desc)
            
            scored = []
            for p in prod_data:
                ratio = SequenceMatcher(None, norm_desc, p["norm_name"]).ratio()
                score = ratio * 55.0
                if p["brand"] and p["brand"] in norm_desc:
                    score += 15.0
                if p["category"] and line_cat and p["category"] == line_cat:
                    score += 15.0
                if score >= 35:
                    scored.append((score, p))
            
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, p in scored[:3]:
                cand = MatchCandidate(
                    invoice_line_id=riga.id,
                    product_id=p["id"],
                    supplier_id=inv.fornitore_id,
                    raw_description=desc,
                    normalized_description=norm_desc,
                    score=Decimal(str(round(score, 2))),
                    reason_json={"score": round(score, 2), "matched_product": p["name"]},
                    block_flag=False,
                )
                candidates_to_add.append(cand)
        
        db.add_all(candidates_to_add)
        await db.commit()
        print(f"Done! Created {len(candidates_to_add)} match candidates successfully.")

asyncio.run(main())
