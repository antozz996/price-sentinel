import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate

async def show():
    async with async_session_factory() as db:
        async with db.begin():
            stmt = select(MatchCandidate).where(MatchCandidate.supplier_id == 11, MatchCandidate.status == "pending")
            candidates = (await db.execute(stmt)).scalars().all()
            for c in candidates:
                # Cerca sku candidato se product_id è valorizzato
                sku = None
                if c.product_id:
                    sku = (await db.execute(select(Product.sku_interno).where(Product.id == c.product_id))).scalar()
                
                print(f"ID: {c.id} | Desc: '{c.raw_description}' | Code: '{c.reason_json.get('supplier_code')}' | SKU: {sku} | Price: {c.reason_json.get('price')} | Pack: {c.reason_json.get('pack_qty')} | Vol: {c.reason_json.get('volume_ml')} | Score: {c.score}%")

if __name__ == "__main__":
    asyncio.run(show())
