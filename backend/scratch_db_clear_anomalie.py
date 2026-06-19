import asyncio
import sys
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory

async def main():
    print("Clearing anomalie...")
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE TABLE anomalie CASCADE"))
        await session.commit()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
