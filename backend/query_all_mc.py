import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import MatchCandidate, Product

async def run():
    async with async_session_factory() as db:
        async with db.begin():
            stmt = select(MatchCandidate)
            res = await db.execute(stmt)
            all_mc = res.scalars().all()
            print(f"Total MatchCandidates: {len(all_mc)}")
            for mc in all_mc:
                print(f"ID: {mc.id} | Supplier: {mc.supplier_id} | Desc: '{mc.raw_description}' | Status: {mc.status}")

if __name__ == "__main__":
    asyncio.run(run())
