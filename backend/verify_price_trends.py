import asyncio
import sys
import os

# Append backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from app.database import async_session_factory
from app.models.fatture import RigaFattura
from app.api.v1.intelligence import get_price_trends

async def test_trends():
    print("Avvio verifica endpoint price-trends...")
    async with async_session_factory() as db:
        # 1. Recupera degli SKU validi matched dal database
        stmt = (
            select(RigaFattura.sku_interno)
            .where(
                RigaFattura.sku_interno.is_not(None),
                RigaFattura.stato_matching == "matched"
            )
            .distinct()
            .limit(3)
        )
        res = await db.execute(stmt)
        skus = [r[0] for r in res.all()]
        
        if not skus:
            print("[INFO] Nessuno SKU associato (matched) trovato nel database.")
            print("[INFO] Il test utilizzerà codici SKU fittizi per verificare l'assenza di eccezioni.")
            skus = ["TEST-SKU-01", "TEST-SKU-02"]
        
        print(f"[OK] SKU selezionati per il test: {skus}")
        
        # 2. Chiama l'endpoint get_price_trends direttamente
        skus_query = ",".join(skus)
        print(f"[RUN] Chiamata a get_price_trends con skus='{skus_query}'...")
        
        trends = await get_price_trends(
            skus=skus_query,
            start_date=None,
            end_date=None,
            location_ids=None,
            fornitore_ids=None,
            _user=None,
            db=db
        )
        
        print("[OK] Endpoint eseguito con successo. Validazione formato risposta:")
        
        # 3. Valida lo schema della risposta
        for sku in skus:
            if sku not in trends:
                print(f"[FAIL] Lo SKU {sku} richiesto non è presente nella risposta.")
                sys.exit(1)
                
            data = trends[sku]
            print(f"\nSKU: {sku}")
            print(f"  - Prodotto Nome: {data.get('prodotto_nome')}")
            print(f"  - Prezzo Contratto Corrente: {data.get('prezzo_contratto_corrente')}")
            
            history = data.get("history", [])
            print(f"  - Numero transazioni trovate: {len(history)}")
            
            if len(history) > 0:
                point = history[0]
                required_keys = ["data", "prezzo_pagato", "quantita", "fornitore", "location", "prezzo_contratto"]
                for key in required_keys:
                    if key not in point:
                        print(f"[FAIL] Il punto storico manca della chiave obbligatoria: '{key}'")
                        sys.exit(1)
                print(f"  - Esempio transazione valida: {point}")
                
        print("\n[SUCCESS] Verifica completata con successo. Tutti i controlli sono passati.")

if __name__ == "__main__":
    asyncio.run(test_trends())
