import asyncio
import sys
import html
from sqlalchemy import select, update

# Ensure app path is in sys.path when running in Docker
sys.path.append("/app")

from app.database import async_session_factory, engine
from app.models.fatture import RigaFattura
from app.models.listino import ListinoMaster

def clean_text(text: str) -> str:
    """Risolve ricorsivamente le entità HTML (es. &amp;deg; -> &deg; -> °)"""
    if not text:
        return text
    prev = ""
    while text != prev:
        prev = text
        text = html.unescape(text)
    return text

async def cleanup_righe_fattura(session):
    print("🧹 Inizio pulizia righe_fattura...")
    # Seleziona tutte le righe che contengono '&' per identificare potenziali entità
    res = await session.execute(
        select(RigaFattura.id, RigaFattura.descrizione_fornitore_raw)
        .where(RigaFattura.descrizione_fornitore_raw.like('%&%'))
    )
    rows = res.all()
    print(f"Trovate {len(rows)} righe_fattura contenenti il simbolo '&'.")
    
    updated_count = 0
    for row_id, raw_desc in rows:
        cleaned = clean_text(raw_desc)
        if cleaned != raw_desc:
            # Aggiornamento sicuro parametrizzato tramite ORM
            await session.execute(
                update(RigaFattura)
                .where(RigaFattura.id == row_id)
                .values(descrizione_fornitore_raw=cleaned)
            )
            updated_count += 1
            if updated_count % 100 == 0:
                print(f"Aggiornate {updated_count} righe...")
                await session.flush()
                
    await session.commit()
    print(f"✅ Aggiornate con successo {updated_count} righe in righe_fattura.")

async def cleanup_listino_master(session):
    print("🧹 Ininizio pulizia listino_master...")
    res = await session.execute(
        select(ListinoMaster.id, ListinoMaster.descrizione)
        .where(ListinoMaster.descrizione.like('%&%'))
    )
    rows = res.all()
    print(f"Trovate {len(rows)} righe in listino_master contenenti il simbolo '&'.")
    
    updated_count = 0
    for row_id, desc in rows:
        cleaned = clean_text(desc)
        if cleaned != desc:
            # Aggiornamento sicuro parametrizzato tramite ORM
            await session.execute(
                update(ListinoMaster)
                .where(ListinoMaster.id == row_id)
                .values(descrizione=cleaned)
            )
            updated_count += 1
            
    await session.commit()
    print(f"✅ Aggiornate con successo {updated_count} righe in listino_master.")

async def main():
    async with async_session_factory() as session:
        try:
            await cleanup_righe_fattura(session)
            await cleanup_listino_master(session)
        except Exception as e:
            await session.rollback()
            print(f"❌ Errore durante la pulizia del database: {e}", file=sys.stderr)
            raise e
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
