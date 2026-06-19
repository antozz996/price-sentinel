import asyncio
import sys
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Check active suppliers
        res_forn = await session.execute(text("SELECT id, nome_azienda FROM fornitori"))
        fornitori = res_forn.all()
        print("🏢 FORNITORI:")
        for f in fornitori:
            print(f" - ID: {f.id} | Nome: {f.nome_azienda}")

        # Count listini by supplier
        res_listini = await session.execute(text(
            "SELECT fornitore_id, COUNT(*), SUM(CASE WHEN data_scadenza IS NULL THEN 1 ELSE 0 END) as active "
            "FROM listino_master GROUP BY fornitore_id"
        ))
        listini_counts = res_listini.all()
        print("\n📈 LISTINO MASTER STATS BY SUPPLIER:")
        for fid, total, active in listini_counts:
            print(f" - Supplier ID: {fid} | Total entries: {total} | Active (data_scadenza IS NULL): {active}")

        # Print a few samples of listino_master
        res_samples = await session.execute(text(
            "SELECT id, fornitore_id, sku_interno, descrizione, prezzo_pattuito, data_scadenza "
            "FROM listino_master ORDER BY id DESC LIMIT 10"
        ))
        samples = res_samples.all()
        print("\n🔬 LAST 10 LISTINO MASTER ENTRIES:")
        for s in samples:
            print(f" - ID: {s.id} | Fornitore: {s.fornitore_id} | SKU: {s.sku_interno} | Desc: {s.descrizione} | Prezzo: €{s.prezzo_pattuito} | Scadenza: {s.data_scadenza}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
