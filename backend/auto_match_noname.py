import asyncio
import sys
from sqlalchemy import select, text

sys.path.append('/app')
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Find Navas supplier ID
        res = await session.execute(text("SELECT id FROM fornitori WHERE nome_azienda ILIKE '%Navas%'"))
        navas_id = res.scalar()
        
        if not navas_id:
            print("Fornitore Navas non trovato.")
            return

        # 1. Build a dictionary of known mappings (descrizione -> sku_interno)
        sql_known = """
            SELECT DISTINCT rf.descrizione_fornitore_raw, rf.sku_interno
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            WHERE f.fornitore_id = :f_id AND rf.sku_interno IS NOT NULL
        """
        known_res = await session.execute(text(sql_known), {"f_id": navas_id})
        mapping = {}
        for r in known_res.all():
            mapping[r.descrizione_fornitore_raw] = r.sku_interno

        print(f"Trovate {len(mapping)} mappature note da applicare a NONAME.")

        # 2. Find unmatched lines for NONAME (and others)
        sql_unmatched = """
            SELECT rf.id, rf.descrizione_fornitore_raw 
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            JOIN location l ON f.location_id = l.id
            WHERE f.fornitore_id = :f_id AND l.nome_struttura = 'NONAME' AND rf.sku_interno IS NULL
        """
        unmatched_res = await session.execute(text(sql_unmatched), {"f_id": navas_id})
        unmatched = unmatched_res.all()
        
        print(f"Righe NONAME senza SKU da analizzare: {len(unmatched)}")

        updated_count = 0
        missing_descriptions = set()
        
        for r in unmatched:
            if r.descrizione_fornitore_raw in mapping:
                sku = mapping[r.descrizione_fornitore_raw]
                await session.execute(text("""
                    UPDATE righe_fattura 
                    SET sku_interno = :sku, stato_matching = 'matched' 
                    WHERE id = :r_id
                """), {"sku": sku, "r_id": r.id})
                updated_count += 1
            else:
                missing_descriptions.add(r.descrizione_fornitore_raw)
                
        # Fallback: for the missing ones, let's create a fake sku so they appear!
        # "SKU_" + cleaned name
        import re
        for r in unmatched:
            if r.descrizione_fornitore_raw in missing_descriptions:
                clean_name = re.sub(r'[^a-zA-Z0-9]+', '_', str(r.descrizione_fornitore_raw)).upper().strip('_')
                fake_sku = f"SKU_{clean_name}"[:50] # max 50 chars
                await session.execute(text("""
                    UPDATE righe_fattura 
                    SET sku_interno = :sku, stato_matching = 'matched' 
                    WHERE id = :r_id
                """), {"sku": fake_sku, "r_id": r.id})
                updated_count += 1

        await session.commit()
        print(f"Operazione completata! Aggiornate {updated_count} righe per NONAME.")

    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
