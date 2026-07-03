import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import RigaFattura, Fattura
from sqlalchemy import select

async def check_sorgesana():
    async with async_session_factory() as db:
        stmt = (
            select(Fattura.data_documento, RigaFattura.prezzo_netto_normalizzato, RigaFattura.quantita, RigaFattura.sku_interno)
            .join(RigaFattura, RigaFattura.fattura_id == Fattura.id)
            .where(
                RigaFattura.descrizione_fornitore_raw.ilike("%sorgesana%"),
                RigaFattura.stato_matching == "matched"
            )
            .order_by(Fattura.data_documento.asc())
        )
        res = await db.execute(stmt)
        rows = res.all()
        print(f"Found {len(rows)} matched transactions for Sorgesana:")
        for r in rows:
            print(f"  Date: {r.data_documento}, Price: {r.prezzo_netto_normalizzato}, Qty: {r.quantita}, SKU: {r.sku_interno}")

if __name__ == "__main__":
    asyncio.run(check_sorgesana())
