import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import Fattura
from sqlalchemy import select, func

async def check_dates():
    async with async_session_factory() as db:
        res = await db.execute(select(func.min(Fattura.data_documento), func.max(Fattura.data_documento)))
        row = res.one()
        print(f"MIN_DATE: {row[0]}, MAX_DATE: {row[1]}")

if __name__ == "__main__":
    asyncio.run(check_dates())
