import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster

async def verify():
    async with async_session_factory() as db:
        async with db.begin():
            # 1. Alias approvati per Navas
            a_stmt = select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == 11)
            aliases = (await db.execute(a_stmt)).scalars().all()
            print(f"--- ALIAS APPROVATI PER NAVAS ({len(aliases)}) ---")
            for a in aliases:
                p_sku = (await db.execute(select(Product.sku_interno).where(Product.id == a.product_id))).scalar()
                print(f"Alias ID: {a.id} | Desc: '{a.raw_description}' | SKU: {p_sku} | Pack: {a.pack_qty} | Vol: {a.volume_ml} | Status: {a.status}")
                
            # 2. Listino Master per Navas
            l_stmt = select(ListinoMaster).where(ListinoMaster.fornitore_id == 11, ListinoMaster.data_scadenza.is_(None))
            prices = (await db.execute(l_stmt)).scalars().all()
            print(f"\n--- PREZZI IN LISTINO MASTER NAVAS ({len(prices)}) ---")
            for p in prices:
                print(f"Listino ID: {p.id} | SKU: {p.sku_interno} | Desc: '{p.descrizione}' | Price: € {p.prezzo_pattuito} | UOM: {p.unita_misura}")
                
            # 3. MatchCandidates per Navas
            mc_pending = (await db.execute(select(MatchCandidate).where(MatchCandidate.supplier_id == 11, MatchCandidate.status == "pending"))).scalars().all()
            mc_resolved = (await db.execute(select(MatchCandidate).where(MatchCandidate.supplier_id == 11, MatchCandidate.status == "resolved"))).scalars().all()
            print(f"\n--- CANDIDATI NAVAS ---")
            print(f"Pending count: {len(mc_pending)}")
            print(f"Resolved count: {len(mc_resolved)}")

if __name__ == "__main__":
    asyncio.run(verify())
