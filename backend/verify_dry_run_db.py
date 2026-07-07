import asyncio
import json
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, delete, and_
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import import_supplier_list_excel

async def count_records(db, supplier_id):
    # Counts only for supplier 10 to isolate results
    alias_stmt = select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == supplier_id)
    alias_res = await db.execute(alias_stmt)
    alias_cnt = len(alias_res.scalars().all())

    listino_stmt = select(ListinoMaster).where(ListinoMaster.fornitore_id == supplier_id)
    listino_res = await db.execute(listino_stmt)
    listino_cnt = len(listino_res.scalars().all())

    cand_stmt = select(MatchCandidate).where(MatchCandidate.supplier_id == supplier_id)
    cand_res = await db.execute(cand_stmt)
    cand_cnt = len(cand_res.scalars().all())

    return alias_cnt, listino_cnt, cand_cnt

async def run_verification():
    import logging
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    supplier_id = 10
    filepath = "data/import_samples/listino_test.xlsx"
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    async with async_session_factory() as db:
        # Clean previous test records
        await db.execute(delete(MatchCandidate).where(MatchCandidate.source_type == "price_list_row"))
        await db.execute(delete(SupplierProductAlias).where(
            and_(
                SupplierProductAlias.supplier_id == supplier_id,
                SupplierProductAlias.raw_description.in_([
                    "BICCHIERE ACQUA 200ML BIANCO",
                    "Tovagliolo monouso 40x40 pz50",
                    "BICCHIERE MULTICOLORE MEDIO",
                    "STRUMENTO MUSICALE XILOFONO DI LEGNO"
                ])
            )
        ))
        await db.execute(delete(ListinoMaster).where(
            and_(
                ListinoMaster.fornitore_id == supplier_id,
                ListinoMaster.descrizione.in_([
                    "BICCHIERE ACQUA 200ML BIANCO",
                    "Tovagliolo monouso 40x40 pz50",
                    "BICCHIERE MULTICOLORE MEDIO",
                    "STRUMENTO MUSICALE XILOFONO DI LEGNO"
                ])
            )
        ))
        await db.commit()

        print("--- VERIFICA DB PRIMA DEL DRY RUN ---")
        a1, l1, c1 = await count_records(db, supplier_id)
        print(f"Numero Alias: {a1}")
        print(f"Numero ListinoMaster: {l1}")
        print(f"Numero MatchCandidate: {c1}")

        print("\n--- ESECUZIONE DRY RUN (dry_run=True) ---")
        res_dry = await import_supplier_list_excel(db=db, supplier_id=supplier_id, file_bytes=file_bytes, dry_run=True)
        
        # We need to construct custom encoder for decimal and date types in json
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, Decimal):
                    return float(obj)
                if isinstance(obj, (date, datetime)):
                    return obj.isoformat()
                return super().default(obj)

        print(f"Risultato JSON Dry-Run (sintesi):")
        print(f"  righe_totali_lette: {res_dry['righe_totali_lette']}")
        print(f"  righe_importate: {res_dry['righe_importate']}")
        print(f"  alias_approvati_creati: {res_dry['alias_approvati_creati']}")
        print(f"  match_candidates_creati: {res_dry['match_candidates_creati']}")
        print(f"  righe_scartate: {res_dry['righe_scartate']}")
        print(f"  errori_parsing: {res_dry['errori_parsing']}")

        # Print raw JSON for dry_run=True preview list (first 2 items for brevity/rich example)
        print(f"\nReal Preview Items (dry_run=True):")
        print(json.dumps(res_dry["preview"][:2], cls=CustomEncoder, indent=2))

        print("\n--- VERIFICA DB DOPO IL DRY RUN ---")
        a2, l2, c2 = await count_records(db, supplier_id)
        print(f"Numero Alias: {a2}")
        print(f"Numero ListinoMaster: {l2}")
        print(f"Numero MatchCandidate: {c2}")
        
        assert a1 == a2, "Errore: il numero di alias è cambiato!"
        assert l1 == l2, "Errore: il numero di ListinoMaster è cambiato!"
        assert c1 == c2, "Errore: il numero di MatchCandidate è cambiato!"
        print("✅ Successo: I conteggi sono rimasti identici post Dry-Run!")

        print("\n--- ESECUZIONE IMPORT REALE (dry_run=False) ---")
        res_real = await import_supplier_list_excel(db=db, supplier_id=supplier_id, file_bytes=file_bytes, dry_run=False)
        await db.commit() # Commit database changes to verify records exist
        
        print(f"Risultato JSON Import Reale (sintesi):")
        print(f"  righe_totali_lette: {res_real['righe_totali_lette']}")
        print(f"  righe_importate: {res_real['righe_importate']}")
        print(f"  alias_approvati_creati: {res_real['alias_approvati_creati']}")
        print(f"  match_candidates_creati: {res_real['match_candidates_creati']}")

        # Print raw JSON for dry_run=False preview items
        print(f"\nReal Preview Items (dry_run=False):")
        print(json.dumps(res_real["preview"][:2], cls=CustomEncoder, indent=2))

        print("\n--- VERIFICA DB DOPO L'IMPORT REALE ---")
        a3, l3, c3 = await count_records(db, supplier_id)
        print(f"Numero Alias: {a3}")
        print(f"Numero ListinoMaster: {l3}")
        print(f"Numero MatchCandidate: {c3}")
        
        assert a3 > a2 or c3 > c2, "Errore: Nessun record aggiunto dopo import reale!"
        print("✅ Successo: I conteggi sono cambiati coerentemente!")

if __name__ == "__main__":
    asyncio.run(run_verification())
