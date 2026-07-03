import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import XMLRaw, Fattura, RigaFattura
from sqlalchemy import select

async def check_today_invoices():
    async with async_session_factory() as db:
        # Query XMLRaw files uploaded today (2026-06-26)
        stmt = (
            select(XMLRaw)
            .where(XMLRaw.data_ricezione >= datetime(2026, 6, 26, 0, 0, 0, tzinfo=timezone.utc))
            .order_by(XMLRaw.data_ricezione.desc())
        )
        res = await db.execute(stmt)
        files = res.scalars().all()
        
        print(f"Found {len(files)} XML files uploaded today:")
        for f in files:
            print(f"\n--- XMLRaw ID: {f.id}, File: {f.nome_file}, Ingestion State: {f.stato_ingestion} ---")
            
            # Find associated invoices
            inv_stmt = select(Fattura).where(Fattura.xml_raw_id == f.id)
            inv_res = await db.execute(inv_stmt)
            invoices = inv_res.scalars().all()
            
            print(f"  Created {len(invoices)} invoice(s):")
            for inv in invoices:
                print(f"    Invoice ID: {inv.id}, Number: '{inv.numero_documento}', Date: {inv.data_documento}, Supplier ID: {inv.fornitore_id}, Location ID: {inv.location_id}, Total: {inv.totale_imponibile}")
                
                # Load lines for this invoice
                lines_stmt = select(RigaFattura).where(RigaFattura.fattura_id == inv.id)
                lines_res = await db.execute(lines_stmt)
                lines = lines_res.scalars().all()
                print(f"    Invoice has {len(lines)} detail lines:")
                for line in lines:
                    print(f"      Line {line.numero_linea}: Desc: '{line.descrizione_fornitore_raw}', Price: {line.prezzo_netto_normalizzato}, Qty: {line.quantita}, Match State: {line.stato_matching}, SKU: {line.sku_interno}")

if __name__ == "__main__":
    asyncio.run(check_today_invoices())
