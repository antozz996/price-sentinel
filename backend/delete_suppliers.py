import asyncio
import sys
from sqlalchemy import select, delete

sys.path.append('/app')

from app.database import async_session_factory, engine
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.alias import AliasProdotto

async def main():
    try:
        pivas_to_delete = ['12345678901', '98765432109']
        async with async_session_factory() as session:
            res = await session.execute(select(Fornitore).where(Fornitore.partita_iva.in_(pivas_to_delete)))
            fornitori = res.scalars().all()
            fornitore_ids = [f.id for f in fornitori]
            
            if not fornitore_ids:
                print("Nessun fornitore trovato con queste P.IVA.")
                return

            print(f"Eliminazione dati per i fornitori ID: {fornitore_ids}")
            
            await session.execute(delete(ListinoMaster).where(ListinoMaster.fornitore_id.in_(fornitore_ids)))
            await session.execute(delete(AliasProdotto).where(AliasProdotto.fornitore_id.in_(fornitore_ids)))
            await session.execute(delete(Fornitore).where(Fornitore.id.in_(fornitore_ids)))
            
            await session.commit()
            print("Fornitori e dipendenze eliminati con successo dal database.")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
