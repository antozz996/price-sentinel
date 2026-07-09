import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product
from app.services.matching import resolve_invoice_line_product
from app.services.normalization import normalize_text, extract_candidate_attributes, infer_category

async def run_debug():
    async with async_session_factory() as db:
        async with db.begin():
            # Inserisci Coca Cola canonico
            p = Product(
                sku_interno="BEV-COCA_COLA_REG-33CL",
                canonical_name="Coca Cola Regular 33 cl",
                brand="Coca Cola",
                category="soft_drink",
                volume_ml=330,
                container_type="vetro",
                comparison_unit="liter",
                is_commodity=True,
                is_active=True
            )
            db.add(p)
            await db.flush()
            
            raw_desc = "COCA COLA 0.33 X 24 VAP VETRO"
            print("=== DEBUG ATTRIBUTI RIGA ===")
            print("Raw desc:", raw_desc)
            print("Normalized desc:", normalize_text(raw_desc))
            print("Line attrs:", extract_candidate_attributes(raw_desc))
            print("Line category (infer_category):", infer_category(raw_desc))
            
            # Esegui risoluzione
            res = await resolve_invoice_line_product(db, fornitore_id=11, raw_description=raw_desc, supplier_code="NAVAS_COC01")
            
            print("\n=== RISULTATI RESOLVER ===")
            print("Decision:", res["decision"])
            print("Score:", res["score"])
            print("Sku rilevato:", res["sku_interno"])
            print("Candidates:")
            for c in res["candidates"]:
                print(f"  * SKU: {c['sku_interno']} | Score: {c['score']} | Block: {c['block']} | Reason: {c['reason_json']}")
            
            # Rollback automatico

if __name__ == "__main__":
    asyncio.run(run_debug())
