import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import Fattura, RigaFattura
from sqlalchemy import select

async def check_invoice():
    async with async_session_factory() as db:
        stmt = select(Fattura).where(Fattura.numero_documento == "12098")
        res = await db.execute(stmt)
        invoices = res.scalars().all()
        
        print(f"Found {len(invoices)} invoices with number '12098':")
        for inv in invoices:
            print(f"  ID: {inv.id}, Date: {inv.data_documento}, Supplier ID: {inv.fornitore_id}, Location ID: {inv.location_id}, Marker: {inv.marker}")
            # Load lines for this invoice
            lines_stmt = select(RigaFattura).where(RigaFattura.fattura_id == inv.id)
            lines_res = await db.execute(lines_stmt)
            lines = lines_res.scalars().all()
            print(f"  Invoice has {len(lines)} detail lines:")
            for line in lines:
                print(f"    Line {line.numero_linea}: Desc: '{line.descrizione_fornitore_raw}', Price: {line.prezzo_netto_normalizzato}, Qty: {line.quantita}, Match State: {line.stato_matching}, SKU: {line.sku_interno}")

if __name__ == "__main__":
    asyncio.run(check_invoice())
