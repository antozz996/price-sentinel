import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import XMLRaw
from sqlalchemy import select

async def check_xml():
    async with async_session_factory() as db:
        # Search for payload containing the invoice number "12098"
        stmt1 = select(XMLRaw).where(XMLRaw.payload.like("%12098%"))
        res1 = await db.execute(stmt1)
        files1 = res1.scalars().all()
        
        print(f"Found {len(files1)} XMLRaw records containing '12098' in payload:")
        for f in files1:
            print(f"  ID: {f.id}, File: {f.nome_file}, Ingestion State: {f.stato_ingestion}, Date: {f.data_ricezione}")
            if f.errore_dettaglio:
                print(f"    Error: {f.errore_dettaglio}")

        # Search for payload containing the product code "ACQUA002"
        stmt2 = select(XMLRaw).where(XMLRaw.payload.like("%ACQUA002%"))
        res2 = await db.execute(stmt2)
        files2 = res2.scalars().all()
        
        print(f"\nFound {len(files2)} XMLRaw records containing 'ACQUA002' in payload:")
        for f in files2:
            print(f"  ID: {f.id}, File: {f.nome_file}, Ingestion State: {f.stato_ingestion}, Date: {f.data_ricezione}")
            if f.errore_dettaglio:
                print(f"    Error: {f.errore_dettaglio}")

        # If nothing found, print the last 5 uploaded files
        if not files1 and not files2:
            print("\nNothing found. Listing the last 5 uploaded files in xml_raw:")
            stmt3 = select(XMLRaw).order_by(XMLRaw.data_ricezione.desc()).limit(5)
            res3 = await db.execute(stmt3)
            files3 = res3.scalars().all()
            for f in files3:
                print(f"  ID: {f.id}, File: {f.nome_file}, Ingestion State: {f.stato_ingestion}, Date: {f.data_ricezione}")
                if f.errore_dettaglio:
                    print(f"    Error: {f.errore_dettaglio}")

if __name__ == "__main__":
    asyncio.run(check_xml())
