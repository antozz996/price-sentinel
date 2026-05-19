import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.models.location import Location, TipologiaLocation
from app.models.fornitori import Fornitore
from sqlalchemy import text

async def main():
    async with async_session_factory() as session:
        # 1. Register Location if not exists
        res = await session.execute(select(Location).where(Location.piva_riferimento == "08345461217"))
        loc = res.scalar_one_or_none()
        if not loc:
            loc = Location(
                nome_struttura="PLAYA EVENTI SRL",
                piva_riferimento="08345461217",
                tipologia=TipologiaLocation.ristorante
            )
            session.add(loc)
            print("Location 'PLAYA EVENTI SRL' registrata!")
        else:
            print("Location 'PLAYA EVENTI SRL' già esistente.")
            
        # 2. Register Supplier if not exists
        res = await session.execute(select(Fornitore).where(Fornitore.partita_iva == "04614711218"))
        forn = res.scalar_one_or_none()
        if not forn:
            forn = Fornitore(
                partita_iva="04614711218",
                nome_azienda="Navas Distribuzione srl",
                attivo_whitelist=True,
                email_contatto="navas@legalmail.it"
            )
            session.add(forn)
            print("Fornitore 'Navas Distribuzione srl' registrato e whitelistato!")
        else:
            forn.attivo_whitelist = True
            print("Fornitore 'Navas Distribuzione srl' già esistente (whitelist attivata).")
            
        await session.flush()
        
        # 3. Truncate files and upload batches to allow a clean re-upload
        await session.execute(text("TRUNCATE TABLE note_di_credito, anomalie, righe_fattura, fatture, xml_raw, upload_batches RESTART IDENTITY CASCADE;"))
        print("Tabelle di ingestion svuotate con successo per consentire un nuovo upload pulito!")
        
        await session.commit()

if __name__ == "__main__":
    asyncio.run(main())
