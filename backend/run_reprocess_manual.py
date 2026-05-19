import asyncio
import sys
from sqlalchemy import select
from app.services.xml_parser import parse_fattura_xml
from app.services.ingestion import process_xml_raw
from app.models.fatture import XMLRaw, Fattura

sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Select XMLRaw records without Fattura
        res = await session.execute(
            select(XMLRaw).outerjoin(Fattura).where(Fattura.id == None)
        )
        xml_raws = res.scalars().all()
        print(f"Found {len(xml_raws)} XMLRaw records to reprocess.")
        
        if len(xml_raws) > 0:
            xml_raw = xml_raws[0]
            print(f"Reprocessing first XMLRaw (ID: {xml_raw.id}, File: {xml_raw.nome_file})...")
            try:
                parsed = parse_fattura_xml(xml_raw.payload)
                if not parsed.is_valid:
                    print(f"Parsing error: {parsed.errori}")
                else:
                    print(f"Parsed successfully. Cessionario: {parsed.piva_cessionario}, Cedente: {parsed.piva_cedente}")
                    report = await process_xml_raw(session, xml_raw.id, parsed)
                    print(f"Report: {report}")
                    # Commit if successful
                    await session.commit()
                    print("Transaction committed successfully!")
            except Exception as e:
                print(f"Exception during reprocessing: {e}")
                await session.rollback()

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
