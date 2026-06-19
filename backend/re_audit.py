import asyncio
import sys
from decimal import Decimal
sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory
from sqlalchemy import select, and_
from app.models.fatture import RigaFattura, StatoMatching
from app.models.anomalie import Anomalia, StatoValidazione
from app.models.listino import ListinoMaster

async def main():
    async with async_session_factory() as session:
        # Find all righe with SKU GIN0020
        righe_res = await session.execute(
            select(RigaFattura).where(
                and_(
                    RigaFattura.sku_interno == 'GIN0020',
                    RigaFattura.stato_matching == StatoMatching.matched
                )
            )
        )
        righe = righe_res.scalars().all()
        
        # Find active listino for GIN0020
        listino_res = await session.execute(
            select(ListinoMaster).where(
                and_(
                    ListinoMaster.sku_interno == 'GIN0020',
                    ListinoMaster.data_scadenza.is_(None)
                )
            )
        )
        listino = listino_res.scalars().first()
        
        if not listino:
            print("Nessun listino attivo per GIN0020")
            return
            
        prezzo_listino = listino.prezzo_pattuito
        
        for riga in righe:
            # check if anomalia already exists
            anomalia_res = await session.execute(
                select(Anomalia).where(Anomalia.riga_fattura_id == riga.id)
            )
            existing = anomalia_res.scalars().first()
            if existing:
                print(f"Anomalia gia esistente per riga {riga.id} - Aggiorno valori")
                delta_unitario = riga.prezzo_netto_normalizzato - prezzo_listino
                if delta_unitario > 0:
                    existing.delta_prezzo = delta_unitario
                    existing.delta_totale = delta_unitario * riga.quantita
                    existing.prezzo_listino_snapshot = prezzo_listino
                    existing.stato_validazione = StatoValidazione.da_verificare
                continue
            
            # calculate delta
            delta_unitario = riga.prezzo_netto_normalizzato - prezzo_listino
            if delta_unitario > 0:
                delta_totale = delta_unitario * riga.quantita
                anomalia = Anomalia(
                    riga_fattura_id=riga.id,
                    delta_prezzo=delta_unitario,
                    delta_totale=delta_totale,
                    prezzo_listino_snapshot=prezzo_listino,
                    prezzo_fatturato_snapshot=riga.prezzo_netto_normalizzato,
                    stato_validazione=StatoValidazione.da_verificare
                )
                session.add(anomalia)
                print(f"Generata anomalia per riga {riga.id}: delta_unitario={delta_unitario}, delta_totale={delta_totale}")
        
        await session.commit()
        print("Processo completato.")

if __name__ == "__main__":
    asyncio.run(main())
