import os
import sys

# Set host to 127.0.0.1 to connect from the host machine to the docker container port
os.environ["POSTGRES_HOST"] = "127.0.0.1"
sys.path.append("/root/PRICE SENTINEL/backend")

import asyncio
from sqlalchemy import text
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Check righe_fattura containing '&'
        res_righe = await session.execute(text(
            "SELECT id, descrizione_fornitore_raw FROM righe_fattura WHERE descrizione_fornitore_raw LIKE '%&%' LIMIT 10"
        ))
        righe = res_righe.all()
        print(f"Righe in DB containing '&':")
        for r in righe:
            print(f" - ID: {r.id} | Desc: {r.descrizione_fornitore_raw}")

        # Check listino_master containing '&'
        res_list = await session.execute(text(
            "SELECT id, descrizione_contratto_raw FROM listino_master WHERE descrizione_contratto_raw LIKE '%&%' LIMIT 10"
        ))
        listini = res_list.all()
        print(f"\nListino master containing '&':")
        for l in listini:
            print(f" - ID: {l.id} | Desc: {l.descrizione_contratto_raw}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
