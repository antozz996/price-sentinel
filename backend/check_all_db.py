import asyncio
import sys
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Check all suppliers
        res_forn = await session.execute(text("SELECT id, nome_azienda, attivo_whitelist, partita_iva FROM fornitori"))
        print("🏢 ALL SUPPLIERS IN DB:")
        for f in res_forn.all():
            print(f" - ID: {f.id} | Nome: {f.nome_azienda} | Whitelist: {f.attivo_whitelist} | P.IVA: {f.partita_iva}")

        # Check total invoices count
        res_fatt = await session.execute(text("SELECT COUNT(*), fornitore_id FROM fatture GROUP BY fornitore_id"))
        print("\n🧾 INVOICES BY SUPPLIER:")
        for count, fid in res_fatt.all():
            print(f" - Supplier ID: {fid} | Invoice count: {count}")

        # Check total listino entries
        res_list = await session.execute(text("SELECT COUNT(*), fornitore_id FROM listino_master GROUP BY fornitore_id"))
        print("\n📈 CONTRACTS BY SUPPLIER:")
        for count, fid in res_list.all():
            print(f" - Supplier ID: {fid} | Contract count: {count}")

        # Check a few rows in righe_fattura
        res_rf = await session.execute(text("SELECT sku_interno, prezzo_netto_normalizzato, descrizione_fornitore_raw FROM righe_fattura LIMIT 5"))
        print("\n🔬 INVOICE LINES SAMPLES:")
        for r in res_rf.all():
            print(f" - SKU: {r.sku_interno} | Raw Desc: {r.descrizione_fornitore_raw} | Norm: {r.prezzo_netto_normalizzato}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
