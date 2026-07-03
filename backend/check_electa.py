import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session_factory
from app.models.fatture import RigaFattura, Fattura
from sqlalchemy import select

async def check_electa():
    async with async_session_factory() as db:
        stmt = (
            select(
                Fattura.data_documento,
                Fattura.numero_documento,
                RigaFattura.prezzo_netto_normalizzato,
                RigaFattura.quantita,
                RigaFattura.descrizione_fornitore_raw,
                RigaFattura.stato_matching,
                RigaFattura.sku_interno
            )
            .join(RigaFattura, RigaFattura.fattura_id == Fattura.id)
            .where(
                RigaFattura.descrizione_fornitore_raw.ilike("%electa%")
            )
            .order_by(Fattura.data_documento.asc())
        )
        res = await db.execute(stmt)
        rows = res.all()
        print(f"Found {len(rows)} total transactions containing 'electa':")
        for r in rows:
            print(f"  Date: {r.data_documento}, Invoice: {r.numero_documento}, Price: {r.prezzo_netto_normalizzato}, Qty: {r.quantita}, Match State: {r.stato_matching}, SKU: {r.sku_interno}, Desc: {r.descrizione_fornitore_raw}")

if __name__ == "__main__":
    asyncio.run(check_electa())
