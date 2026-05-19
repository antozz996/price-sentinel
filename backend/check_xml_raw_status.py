import asyncio
import sys
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Check XML Raw records and status
        res = await session.execute(text("SELECT COUNT(*) FROM xml_raw"))
        total_xmls = res.scalar()
        print(f"Total XMLs in xml_raw: {total_xmls}")
        
        if total_xmls > 0:
            res_status = await session.execute(text(
                "SELECT stato_ingestion, COUNT(*) as count FROM xml_raw GROUP BY stato_ingestion"
            ))
            print("\nIngestion status breakdown:")
            for r in res_status.all():
                print(f" - {r.stato_ingestion}: {r.count}")
                
            res_errors = await session.execute(text(
                "SELECT errore_dettaglio, COUNT(*) as count FROM xml_raw WHERE errore_dettaglio IS NOT NULL GROUP BY errore_dettaglio"
            ))
            errors = res_errors.all()
            if errors:
                print("\nError detail breakdown:")
                for r in errors:
                    print(f" - {r.errore_dettaglio}: {r.count}")
            
            # Let's inspect unique receiver (cessionario) VATs in xml_raw
            # We can parse them or look at what's happening.
            # But we can also check if there are locations in the database.
            res_locations = await session.execute(text("SELECT COUNT(*) FROM location"))
            total_locations = res_locations.scalar()
            print(f"\nRegistered locations in DB: {total_locations}")
            if total_locations > 0:
                res_loc_list = await session.execute(text("SELECT id, nome_struttura, piva_riferimento FROM location"))
                for l in res_loc_list.all():
                    print(f" - ID {l.id}: '{l.nome_struttura}' (P.IVA: {l.piva_riferimento})")
            
            res_suppliers = await session.execute(text("SELECT COUNT(*) FROM fornitori"))
            total_suppliers = res_suppliers.scalar()
            print(f"Registered suppliers in DB: {total_suppliers}")
            if total_suppliers > 0:
                res_sup_list = await session.execute(text("SELECT id, nome_azienda, partita_iva FROM fornitori"))
                for s in res_sup_list.all():
                    print(f" - ID {s.id}: '{s.nome_azienda}' (P.IVA: {s.partita_iva})")
        else:
            print("\nDatabase is completely empty of XMLs.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
