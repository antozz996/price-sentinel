import asyncio
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, delete, and_

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import import_supplier_list_excel, save_append_only_price
from app.services.order_resolver import resolve_order_item


async def run_import_test():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Excel Listino Import Verification (Fase 3)")
    print("=" * 60)

    # 1. Carica il file Excel di test
    filepath = "data/import_samples/listino_test.xlsx"
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    async with async_session_factory() as db:
        # Pulisci record di precedenti test per garantire isolamento
        await db.execute(delete(MatchCandidate).where(MatchCandidate.source_type == "price_list_row"))
        await db.execute(delete(SupplierProductAlias).where(
            and_(
                SupplierProductAlias.supplier_id == 10,
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
                ListinoMaster.fornitore_id == 10,
                ListinoMaster.descrizione.in_([
                    "BICCHIERE ACQUA 200ML BIANCO",
                    "Tovagliolo monouso 40x40 pz50",
                    "BICCHIERE MULTICOLORE MEDIO",
                    "STRUMENTO MUSICALE XILOFONO DI LEGNO"
                ])
            )
        ))
        await db.commit()

        # [Passo 0] Esecuzione import Excel in modalità DRY_RUN
        print("\n[Passo 0] Esecuzione import Excel in modalità DRY_RUN (dry_run=True)...")
        res_dry = await import_supplier_list_excel(db=db, supplier_id=10, file_bytes=file_bytes, dry_run=True)
        
        print(f"  [DRY] Righe lette: {res_dry['righe_totali_lette']}")
        print(f"  [DRY] Righe importate (Auto-Match previste): {res_dry['righe_importate']}")
        print(f"  [DRY] Alias approvati creati previsti: {res_dry['alias_approvati_creati']}")
        print(f"  [DRY] Match candidates creati previsti: {res_dry['match_candidates_creati']}")
        print(f"  [DRY] Preview length: {len(res_dry['preview'])}")

        # Verifiche statistiche dry_run
        assert res_dry["righe_totali_lette"] == 5
        assert res_dry["righe_importate"] == 1
        assert res_dry["match_candidates_creati"] == 4
        assert res_dry["dry_run"] is True

        # Verifica campi preview richiesti
        preview_row = res_dry["preview"][0]
        required_keys = [
            "raw_description", "supplier_code", "normalized_description", 
            "price", "uom", "pack_qty", "volume_ml", "category", 
            "matched_sku", "score", "match_reason", "decision", "warning"
        ]
        for key in required_keys:
            assert key in preview_row, f"Chiave preview mancante nel dry run: {key}"
        print("  ✅ Tutti i campi richiesti sono presenti nell'anteprima del dry run!")

        # Verifica che il DB sia rimasto pulito
        cand_db_count = (await db.execute(select(MatchCandidate).where(MatchCandidate.supplier_id == 10))).scalars().all()
        alias_db_count = (await db.execute(select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == 10))).scalars().all()
        
        # Filtriamo solo quelli che abbiamo pulito prima (per evitare di contare i dati seed originari del db)
        cand_db_clean = [c for c in cand_db_count if c.source_type == "price_list_row"]
        alias_db_clean = [a for a in alias_db_count if a.raw_description in ["BICCHIERE ACQUA 200ML BIANCO", "Tovagliolo monouso 40x40 pz50"]]
        
        assert len(cand_db_clean) == 0, f"Errore: Trovati {len(cand_db_clean)} candidati nel DB durante dry_run!"
        assert len(alias_db_clean) == 0, f"Errore: Trovati {len(alias_db_clean)} alias nel DB durante dry_run!"
        print("  ✅ Modalità DRY_RUN non ha scritto nulla a DB ed ha restituito statistiche corrette!")

        # [Passo 1] Esecuzione import Excel reale (dry_run=False)
        print("\n[Passo 1] Esecuzione import reale (dry_run=False) per Eurocarta (ID 10)...")
        res = await import_supplier_list_excel(db=db, supplier_id=10, file_bytes=file_bytes, dry_run=False)
        
        print(f"  Righe lette: {res['righe_totali_lette']}")
        print(f"  Righe importate (Auto-Match): {res['righe_importate']}")
        print(f"  Alias approvati creati: {res['alias_approvati_creati']}")
        print(f"  Alias già esistenti riconosciuti: {res['alias_gia_esistenti_riconosciuti']}")
        print(f"  Prezzi nuovi creati: {res['prezzi_nuovi_creati']}")
        print(f"  Match candidates creati: {res['match_candidates_creati']}")
        print(f"  Errori di parsing: {len(res['errori_parsing'])}")

        # Assertions primo import reale
        assert res["righe_totali_lette"] == 5, f"Lette {res['righe_totali_lette']} invece di 5"
        assert res["righe_importate"] == 1, f"Matched {res['righe_importate']} invece di 1"
        assert res["match_candidates_creati"] == 4, f"Candidati {res['match_candidates_creati']} invece di 4"
        assert (res["prezzi_nuovi_creati"] + res["prezzi_invariati"]) == 1, f"Prezzi {res['prezzi_nuovi_creati'] + res['prezzi_invariati']} invece di 1"
        assert res["dry_run"] is False
        print("  ✅ Primo import reale superato con successo!")

        # 2. Verifica candidati in Parking Area (con score 70-89 e < 70)
        print("\n[Passo 2] Verifica Match Candidates e score 70-89...")
        stmt_cand = select(MatchCandidate).where(MatchCandidate.source_type == "price_list_row").order_by(MatchCandidate.score.desc())
        cands = (await db.execute(stmt_cand)).scalars().all()
        
        cand_70_89 = None
        for c in cands:
            print(f"  Candidato: '{c.raw_description}' | Score: {c.score} | Linked Product ID: {c.product_id}")
            if c.raw_description == "BICCHIERE ACQUA 200ML BIANCO":
                cand_70_89 = c
                assert c.score >= 70.0 and c.score < 90.0, f"Score non corretto per candidato 70-89: {c.score}"
                assert c.product_id is not None, "Il candidato 70-89 deve avere il product_id valorizzato!"
            elif c.score < 70.0:
                assert c.product_id is None, f"Candidato {c.raw_description} con score < 70 ({c.score}) ha product_id!"
                
            # Verifica che il prezzo non sia in ListinoMaster (Fase pre-approvazione)
            stmt_lm_pre = select(ListinoMaster).where(
                and_(ListinoMaster.fornitore_id == 10, ListinoMaster.descrizione == c.raw_description)
            )
            lm_pre = (await db.execute(stmt_lm_pre)).scalars().first()
            assert lm_pre is None, f"Errore: Prezzo salvato in ListinoMaster pre-approvazione per: {c.raw_description}"

        assert cand_70_89 is not None, "Dovrebbe esserci un candidato per BICCHIERE ACQUA 200ML BIANCO nella fascia 70-89!"
        print("  ✅ Verifica Match Candidates e score 70-89 superata!")

        # 3. Verifica Approvazione Manuale (Punto 2)
        print("\n[Passo 3] Test di approvazione manuale del candidato dubbio...")
        
        # Pre-approvazione checks per cand_70_89
        stmt_alias_pre = select(SupplierProductAlias).where(
            and_(
                SupplierProductAlias.supplier_id == 10,
                SupplierProductAlias.raw_description == cand_70_89.raw_description
            )
        )
        alias_pre = (await db.execute(stmt_alias_pre)).scalars().first()
        assert alias_pre is None, "L'alias non deve esistere prima dell'approvazione!"

        # Eseguiamo il flusso di approvazione
        prod_obj = await db.get(Product, cand_70_89.product_id)
        assert prod_obj is not None
        
        # A. Crea alias
        new_alias = SupplierProductAlias(
            supplier_id=10,
            product_id=prod_obj.id,
            supplier_code=cand_70_89.reason_json.get("supplier_code"),
            raw_description=cand_70_89.raw_description,
            normalized_description=cand_70_89.normalized_description,
            status="approved",
            source="manual",
            confidence_score=1.0
        )
        db.add(new_alias)
        
        # B. Salva prezzo in ListinoMaster prendendolo da reason_json (Punto 12)
        price_val = cand_70_89.reason_json.get("price")
        uom_val = cand_70_89.reason_json.get("uom") or prod_obj.comparison_unit or "piece"
        
        await db.flush()
        await save_append_only_price(
            db=db,
            fornitore_id=10,
            sku_interno=prod_obj.sku_interno,
            descrizione=cand_70_89.raw_description,
            prezzo_pattuito=Decimal(str(price_val)),
            unita_misura=uom_val,
            data_inizio=date.today(),
            supplier_product_alias_id=new_alias.id
        )
        
        # C. Aggiorna stato del candidato
        cand_70_89.status = "approved"
        cand_70_89.resolved_at = datetime.utcnow()
        await db.flush()

        # Post-approvazione checks
        alias_post = (await db.execute(stmt_alias_pre)).scalars().first()
        assert alias_post is not None and alias_post.status == "approved", "L'alias deve essere approved post-approvazione!"
        
        stmt_lm_post = select(ListinoMaster).where(
            and_(
                ListinoMaster.fornitore_id == 10,
                ListinoMaster.sku_interno == prod_obj.sku_interno,
                ListinoMaster.descrizione == cand_70_89.raw_description
            )
        )
        lm_post = (await db.execute(stmt_lm_post)).scalars().first()
        assert lm_post is not None and lm_post.prezzo_pattuito == Decimal("3.20"), "Il prezzo a listino deve corrispondere a 3.20!"
        assert cand_70_89.status == "approved", "Lo stato del candidato non è approved!"
        print("  ✅ Approvazione manuale verificata con successo!")

        # 4. Verifica Idempotenza
        print("\n[Passo 4] Esecuzione secondo import reale dello stesso file (Idempotenza)...")
        res2 = await import_supplier_list_excel(db=db, supplier_id=10, file_bytes=file_bytes, dry_run=False)
        
        print(f"  Righe lette: {res2['righe_totali_lette']}")
        print(f"  Righe importate: {res2['righe_importate']}")
        print(f"  Prezzi invariati: {res2['prezzi_invariati']}")
        print(f"  Match candidates creati (dovrebbero essere 0): {res2['match_candidates_creati']}")
        
        # Post-approvazione sia caffè che acqua sono importati automaticamente come contratti attivi
        assert res2["righe_importate"] == 2, f"Matched {res2['righe_importate']} invece di 2"
        assert (res2["prezzi_invariati"] + res2["prezzi_nuovi_creati"]) == 2, "Idempotenza fallita: i prezzi non sono stati riconosciuti come invariati"
        assert res2["match_candidates_creati"] == 0, "Idempotenza fallita: sono stati creati candidati duplicati"
        print("  ✅ Test Idempotenza superato!")

        # 5. Resolve ordine per un prodotto importato
        print("\n[Passo 5] Esecuzione resolver ordine dopo l'importazione ed approvazione...")
        res_resolve = await resolve_order_item(
            db=db,
            query="BICCHIERE ACQUA",
            requested_qty=Decimal("10"),
            requested_unit="piece",
            allow_equivalent=True
        )
        print(f"  Risoluzione: query '{res_resolve['query']}' -> SKU '{res_resolve['matched_product']['sku_interno']}'")
        best = res_resolve["best_offer"]
        print(f"  Miglior offerta: Fornitore = {best['supplier_name']}, Prezzo pack = € {best['price_per_pack']}, Confezioni = {best['packs_needed']}, Totale = € {best['estimated_total']}")
        
        assert res_resolve["decision"] == "resolved", "Risoluzione fallita per Bicchiere"
        assert best["supplier_name"] == "Eurocarta", "Fornitore errato per Bicchiere"
        assert Decimal(best["price_per_pack"]) == Decimal("3.2000"), f"Prezzo errato: {best['price_per_pack']}"
        print("  ✅ Risoluzione ordine post-import superata!")

    print("\n🎉 TUTTI I TEST DI IMPORTAZIONE EXCEL, DRY_RUN E IDEMPOTENZA SONO STATI SUPERATI CON SUCCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    from sqlalchemy import delete
    asyncio.run(run_import_test())
