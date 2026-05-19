import asyncio
import sys
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # count righe
        res_righe = await session.execute(text("SELECT COUNT(*) FROM righe_fattura"))
        count_righe = res_righe.scalar()
        print(f"Righe in DB: {count_righe}")

        # check what is in righe_fattura (sku_interno)
        res_sku = await session.execute(text("SELECT sku_interno IS NOT NULL as has_sku, COUNT(*) FROM righe_fattura GROUP BY has_sku"))
        sku_groups = res_sku.all()
        print(f"\nSKU groups in righe_fattura:")
        for has_sku, count in sku_groups:
            print(f" - Has SKU: '{has_sku}', Count: {count}")

        # check sku_manager query
        sql = """
            SELECT 
                sku_interno, 
                MAX(descrizione_fornitore_raw) as nome_prodotto,
                COUNT(id) as total_acquisti
            FROM righe_fattura 
            WHERE sku_interno IS NOT NULL 
            GROUP BY sku_interno
            ORDER BY total_acquisti DESC
            LIMIT 5
        """
        res_manager = await session.execute(text(sql))
        print("\nTop 5 SKUs in catalog:")
        for r in res_manager.all():
            print(f" - SKU: {r.sku_interno}, Prodotto: {r.nome_prodotto}, Acquisti: {r.total_acquisti}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
