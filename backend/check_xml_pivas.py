import asyncio
import sys
from sqlalchemy import text
from app.services.xml_parser import parse_fattura_xml

sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Load all xml_payloads
        res = await session.execute(text("SELECT id, payload, nome_file FROM xml_raw"))
        xmls = res.all()
        
        print(f"Total XML files in DB: {len(xmls)}")
        
        # Load active suppliers and locations in DB
        res_loc = await session.execute(text("SELECT piva_riferimento FROM location"))
        registered_locations = {r.piva_riferimento for r in res_loc.all()}
        
        res_forn = await session.execute(text("SELECT partita_iva FROM fornitori"))
        registered_suppliers = {r.partita_iva for r in res_forn.all()}
        
        print(f"Registered Location P.IVAs: {registered_locations}")
        print(f"Registered Supplier P.IVAs: {registered_suppliers}\n")
        
        unregistered_locs = {}
        unregistered_forns = {}
        processed_successfully = 0
        skipped_forn = 0
        skipped_loc = 0
        
        for xml_id, payload, nome_file in xmls:
            try:
                parsed = parse_fattura_xml(payload)
                if not parsed.is_valid:
                    continue
                
                cedente_piva = parsed.piva_cedente
                cedente_nome = parsed.denominazione_cedente or "Fornitore Sconosciuto"
                cessionario_piva = parsed.piva_cessionario
                cessionario_nome = parsed.denominazione_cessionario or "Location Sconosciuta"
                
                is_forn_ok = cedente_piva in registered_suppliers
                is_loc_ok = cessionario_piva in registered_locations
                
                if is_forn_ok and is_loc_ok:
                    processed_successfully += 1
                else:
                    if not is_forn_ok:
                        skipped_forn += 1
                        unregistered_forns[cedente_piva] = cedente_nome
                    if not is_loc_ok:
                        skipped_loc += 1
                        unregistered_locs[cessionario_piva] = cessionario_nome
            except Exception as e:
                print(f"Error parsing XML {xml_id}: {e}")
                
        print("--- ANALYSIS OF UPLOADED INVOICES ---")
        print(f"Invoices that WOULD process successfully: {processed_successfully}")
        print(f"Invoices blocked by Unregistered Supplier: {skipped_forn}")
        print(f"Invoices blocked by Unregistered Location: {skipped_loc}")
        
        print("\nUnregistered Suppliers found in XMLs:")
        for piva, nome in unregistered_forns.items():
            print(f" - P.IVA: {piva} -> '{nome}'")
            
        print("\nUnregistered Locations found in XMLs:")
        for piva, nome in unregistered_locs.items():
            print(f" - P.IVA: {piva} -> '{nome}'")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
