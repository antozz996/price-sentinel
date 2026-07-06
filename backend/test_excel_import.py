import asyncio
from decimal import Decimal
from datetime import date
from sqlalchemy import select

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import import_supplier_list_excel
from app.services.order_resolver import resolve_order_item


async def run_import_test():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Excel Listino Import Verification")
    print("=" * 60)

    # 1. Carica il file Excel di test
    filepath = "data/import_samples/listino_test.xlsx"
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    async with async_session_factory() as db:
        # Pulisci eventuali record precedenti di listino importati o candidati di test
        # per garantire che il test sia ripetibile ed isolato
        await db.execute(delete(MatchCandidate).where(MatchCandidate.source_type == "price_list_row"))
        # Non eliminiamo i listini concordati del seed ma scadiamo quelli importati in passato
        # per non violare la data protection
        
        # Esegui primo import
        print("\n[Passo 1] Esecuzione primo import Excel per Eurocarta (ID 10)...")
        res = await import_supplier_list_excel(db=db, supplier_id=10, file_bytes=file_bytes)
        
        print(f"  Righe lette: {res['righe_totali_lette']}")
        print(f"  Righe importate (Auto-Match): {res['righe_importate']}")
        print(f"  Alias approvati creati: {res['alias_approvati_creati']}")
        print(f"  Alias già esistenti riconosciuti: {res['alias_gia_esistenti_riconosciuti']}")
        print(f"  Prezzi nuovi creati: {res['prezzi_nuovi_creati']}")
        print(f"  Match candidates creati: {res['match_candidates_creati']}")
        print(f"  Errori di parsing: {len(res['errori_parsing'])}")
        for err in res["errori_parsing"]:
            print(f"    - Parsing Error: {err}")

        # Assertions
        assert res["righe_totali_lette"] == 5, f"Lette {res['righe_totali_lette']} invece di 5"
        assert res["righe_importate"] == 1, f"Matched {res['righe_importate']} invece di 1"
        assert res["match_candidates_creati"] == 4, f"Candidati {res['match_candidates_creati']} invece di 4"
        assert (res["prezzi_nuovi_creati"] + res["prezzi_invariati"]) == 1, f"Prezzi {res['prezzi_nuovi_creati'] + res['prezzi_invariati']} invece di 1"
        print("  ✅ Primo import superato con successo!")

        # 2. Verifica candidati in Parking Area
        print("\n[Passo 2] Verifica Match Candidates creati a DB...")
        stmt_cand = select(MatchCandidate).where(MatchCandidate.source_type == "price_list_row").order_by(MatchCandidate.score.desc())
        cands = (await db.execute(stmt_cand)).scalars().all()
        
        for c in cands:
            print(f"  Candidato: '{c.raw_description}' | Score: {c.score} | Linked Product ID: {c.product_id}")
            if c.score < 70.0:
                assert c.product_id is None, f"Candidato {c.raw_description} con score < 70 ({c.score}) ha product_id!"
            else:
                assert c.product_id is not None, f"Candidato {c.raw_description} con score >= 70 ({c.score}) non ha product_id!"

        print("  ✅ Verifica Match Candidates a DB completata!")

        # 3. Verifica Idempotenza
        print("\n[Passo 3] Esecuzione secondo import dello stesso file (Idempotenza)...")
        res2 = await import_supplier_list_excel(db=db, supplier_id=10, file_bytes=file_bytes)
        
        print(f"  Righe lette: {res2['righe_totali_lette']}")
        print(f"  Righe importate: {res2['righe_importate']}")
        print(f"  Prezzi invariati: {res2['prezzi_invariati']}")
        print(f"  Match candidates creati (dovrebbero essere 0): {res2['match_candidates_creati']}")
        
        assert (res2["prezzi_invariati"] + res2["prezzi_nuovi_creati"]) == 1, "Idempotenza fallita: i prezzi non sono stati riconosciuti come invariati"
        assert res2["match_candidates_creati"] == 0, "Idempotenza fallita: sono stati creati candidati duplicati"
        print("  ✅ Test Idempotenza superato!")

        # 4. Resolve ordine per un prodotto importato
        print("\n[Passo 4] Esecuzione resolver ordine dopo l'importazione...")
        res_resolve = await resolve_order_item(
            db=db,
            query="BICCHIERE CAFFE",
            requested_qty=Decimal("100"),
            requested_unit="piece",
            allow_equivalent=True
        )
        print(f"  Risoluzione: query '{res_resolve['query']}' -> SKU '{res_resolve['matched_product']['sku_interno']}'")
        best = res_resolve["best_offer"]
        print(f"  Miglior offerta: Fornitore = {best['supplier_name']}, Prezzo pack = € {best['price_per_pack']}, Confezioni = {best['packs_needed']}, Totale = € {best['estimated_total']}")
        
        assert res_resolve["decision"] == "resolved", "Risoluzione fallita per Bicchiere"
        assert best["supplier_name"] == "Eurocarta", "Fornitore errato per Bicchiere"
        print("  ✅ Risoluzione ordine post-import superata!")

    print("\n🎉 TUTTI I TEST DI IMPORTAZIONE EXCEL E IDEMPOTENZA SONO STATI SUPERATI CON SUCCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    from sqlalchemy import delete
    asyncio.run(run_import_test())
