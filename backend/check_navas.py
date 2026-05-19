import asyncio
import sys
from sqlalchemy import select, text

sys.path.append('/app')
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Find Navas supplier ID
        res = await session.execute(text("SELECT id, nome_azienda FROM fornitori WHERE nome_azienda ILIKE '%Navas%'"))
        fornitore = res.first()
        
        if not fornitore:
            print("Fornitore Navas non trovato.")
            return
            
        print(f"Trovato Fornitore: {fornitore.nome_azienda} (ID: {fornitore.id})")
        
        # Check righe fattura for Navas
        sql = """
            SELECT 
                COUNT(*) as total_righe,
                SUM(CASE WHEN rf.sku_interno IS NOT NULL THEN 1 ELSE 0 END) as righe_con_sku,
                SUM(CASE WHEN rf.sku_interno IS NULL THEN 1 ELSE 0 END) as righe_senza_sku
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            WHERE f.fornitore_id = :f_id
        """
        stats_res = await session.execute(text(sql), {"f_id": fornitore.id})
        stats = stats_res.one()
        
        print(f"Righe Totali Navas: {stats.total_righe}")
        print(f"Righe CON sku_interno: {stats.righe_con_sku}")
        print(f"Righe SENZA sku_interno: {stats.righe_senza_sku}")
        
        # Check if PLAYA EVENTI has SKUs for Navas
        sql_playa = """
            SELECT 
                COUNT(*) as total_righe,
                SUM(CASE WHEN rf.sku_interno IS NOT NULL THEN 1 ELSE 0 END) as righe_con_sku
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            JOIN location l ON f.location_id = l.id
            WHERE f.fornitore_id = :f_id AND l.nome_struttura = 'PLAYA EVENTI SRL'
        """
        stats_playa = (await session.execute(text(sql_playa), {"f_id": fornitore.id})).one()
        
        print(f"\nDi cui per PLAYA EVENTI SRL:")
        print(f"Righe Totali: {stats_playa.total_righe}")
        print(f"Righe CON sku_interno: {stats_playa.righe_con_sku}")

    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
