import asyncio
import sys
from sqlalchemy import select, text

sys.path.append('/app')

from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Check locations
        print("--- LOCATIONS ---")
        loc_res = await session.execute(text("SELECT id, nome_struttura FROM location"))
        for r in loc_res.all():
            print(f"ID: {r.id}, Nome: {r.nome_struttura}")
            
        print("\n--- FATTURE FOR NONAME ---")
        fat_res = await session.execute(text("""
            SELECT f.id, f.location_id, l.nome_struttura 
            FROM fatture f
            JOIN location l ON f.location_id = l.id
            WHERE l.nome_struttura = 'NONAME'
        """))
        fatture = fat_res.all()
        fattura_ids = [f.id for f in fatture]
        print(f"Trovate {len(fatture)} fatture per NONAME.")
        
        if fattura_ids:
            print("\n--- RIGHE FATTURA FOR NONAME ---")
            rf_res = await session.execute(text(f"""
                SELECT count(*) as total,
                       sum(case when sku_interno is not null then 1 else 0 end) as with_sku,
                       sum(case when stato_matching = 'matched' then 1 else 0 end) as matched
                FROM righe_fattura 
                WHERE fattura_id IN ({','.join(map(str, fattura_ids))})
            """))
            stats = rf_res.one()
            print(f"Totale righe: {stats.total}")
            print(f"Righe con sku_interno: {stats.with_sku}")
            print(f"Righe con stato_matching='matched': {stats.matched}")

    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
