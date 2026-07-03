import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.location import Location
from sqlalchemy import select

async def check_locations():
    async with async_session_factory() as db:
        stmt = select(Location)
        res = await db.execute(stmt)
        locations = res.scalars().all()
        print(f"Found {len(locations)} locations in database:")
        for loc in locations:
            print(f"  ID: {loc.id}, Name: {loc.nome_struttura}, P.IVA: {loc.piva_riferimento}")

if __name__ == "__main__":
    asyncio.run(check_locations())
