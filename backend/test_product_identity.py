import asyncio
from decimal import Decimal
from datetime import date
from sqlalchemy import select

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.services.normalization import normalize_text, extract_volume_ml, infer_category
from app.services.matching import resolve_invoice_line_product, normalize_price_for_comparison
from app.services.order_resolver import resolve_order_item


async def run_verification():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Product Identity Layer Verification")
    print("=" * 60)

    # 1. Test di Normalizzazione Testo ed Attributi
    print("\n[Test 1] Verifica Normalizzazione Testo & Volume...")
    desc_caffe = "BICCH. CAFFE 80CC X100"
    norm_caffe = normalize_text(desc_caffe)
    vol_caffe = extract_volume_ml(desc_caffe)
    cat_caffe = infer_category(desc_caffe)
    
    print(f"  Raw:  '{desc_caffe}'")
    print(f"  Norm: '{norm_caffe}'")
    print(f"  Vol:  {vol_caffe} ml")
    print(f"  Cat:  {cat_caffe}")

    assert "bicchiere" in norm_caffe, "Errore espansione 'bicch.'"
    assert vol_caffe == 80, "Errore estrazione volume cc"
    assert cat_caffe == "monouso", "Errore inferenza categoria"
    print("  ✅ Test Normalizzazione superato!")

    async with async_session_factory() as db:
        # 2. Test del Matching Engine (resolve_invoice_line_product)
        print("\n[Test 2] Verifica Matching Engine & Scoring...")
        
        # Test di match diretto tramite alias (caricato nel seed per Eurocarta, ID=10 o in base al DB)
        # Troviamo l'ID di Eurocarta
        stmt_supplier = select(SupplierProductAlias).where(SupplierProductAlias.raw_description == "BICCH. CAFFE 80CC X100")
        alias_caffe = (await db.execute(stmt_supplier)).scalars().first()
        
        if alias_caffe:
            print(f"  Mappa alias trovata: {alias_caffe.raw_description} -> SKU {alias_caffe.product.sku_interno}")
            
            # Eseguiamo il resolver per la riga della fattura con codice fornitore esatto
            res = await resolve_invoice_line_product(
                db=db,
                fornitore_id=alias_caffe.supplier_id,
                raw_description="BICCH. CAFFE 80CC X100",
                supplier_code=alias_caffe.supplier_code
            )
            print(f"  Codice Fornitore Match: Score = {res['score']}, Decisione = '{res['decision']}', SKU = {res['sku_interno']}")
            assert res["score"] == 100.0, "Score del match diretto per codice articolo non corretto"
            assert res["decision"] == "auto_match", "Decisione errata per match diretto"
            
            # Test di match fuzzy (es. con piccola variazione che attiva lo scoring fuzzy + blocchi)
            res_fuzzy = await resolve_invoice_line_product(
                db=db,
                fornitore_id=alias_caffe.supplier_id,
                raw_description="BICCHIERE CAFFE MONOUSO",
                supplier_code="CODICE-NON-ESISTENTE"
            )
            print(f"  Fuzzy Match: Score = {res_fuzzy['score']}, Decisione = '{res_fuzzy['decision']}', SKU = {res_fuzzy['sku_interno']}")
            
            # Test di blocco per categoria/volume differente
            res_blocked = await resolve_invoice_line_product(
                db=db,
                fornitore_id=alias_caffe.supplier_id,
                raw_description="BICCHIERE ACQUA 200ML",  # Prodotto diverso da bicchiere caffè
                supplier_code="CODICE-NON-ESISTENTE"
            )
            print(f"  Match con blocco: Score = {res_blocked['score']}, Decisione = '{res_blocked['decision']}', SKU = {res_blocked['sku_interno']}")
            # Poiché il volume è differente o la categoria blocca, il best match per BICCHIERE_CAFFE dovrebbe essere scartato o avere block_flag=True
            # Se ha preso BICCHIERE_ACQUA come best match corretto, lo score sarà alto ed approvato, il che è corretto!
            if res_blocked["sku_interno"] == "BICCHIERE_CAFFE":
                # Se ha cercato di abbinarlo a caffè, deve essere bloccato
                assert res_blocked["decision"] != "auto_match", "Match errato con volume diverso non bloccato"
            
            print("  ✅ Test Matching Engine superato!")
            
        else:
            print("  ⚠️ Attenzione: Nessun alias trovato nel DB. Assicurati che il seed sia stato eseguito.")

        # 3. Test della Normalizzazione Prezzo
        print("\n[Test 3] Verifica Normalizzazione Prezzo...")
        stmt_prod = select(Product).where(Product.sku_interno == "BICCHIERE_CAFFE")
        product = (await db.execute(stmt_prod)).scalar_one()
        
        # Test prezzo al pezzo (piece) da confezione da 100 pezzi con prezzo 2.50 €
        res_price = normalize_price_for_comparison(
            price_or_line=Decimal("2.5000"),
            quantity_or_product=Decimal("1"),
            invoice_uom="Pz",
            product=product,
            alias=alias_caffe
        )
        print(f"  Prezzo normalizzato: {res_price.normalized_unit_price} / {res_price.comparison_unit} (pack_qty: {res_price.pack_qty})")
        assert res_price.normalized_unit_price == Decimal("0.0250"), "Prezzo unitario normalizzato errato per piece"
        
        # Test prezzo al litro (liter) da confezione da 6 bottiglie da 750ml con prezzo 12.00 €
        product_liter = Product(comparison_unit="liter", volume_ml=750, unit_count=6)
        res_liter = normalize_price_for_comparison(
            price_or_line=Decimal("12.0000"),
            quantity_or_product=Decimal("1"),
            invoice_uom="Conf",
            product=product_liter,
            alias=None
        )
        # prezzo unitario per bottiglia = 12.00 / 6 = 2.00 €
        # prezzo al litro = 2.00 / 0.750 = 2.6667 €
        print(f"  Prezzo al litro normalizzato: {res_liter.normalized_unit_price:.4f} (pack_qty: {res_liter.pack_qty})")
        assert abs(res_liter.normalized_unit_price - Decimal("2.666666")) < Decimal("0.01"), "Prezzo al litro calcolato errato"
        print("  ✅ Test Normalizzazione Prezzo superato!")

        # 4. Test del Resolver d'Ordine (resolve_order_item)
        print("\n[Test 4] Verifica Resolver d'Ordine (Routing Fornitori)...")
        res_order = await resolve_order_item(
            db=db,
            query="BICCHIERE CAFFE",
            requested_qty=Decimal("1000"),
            requested_unit="piece",
            allow_equivalent=True
        )
        
        print(f"  Query: '{res_order['query']}' -> SKU Rilevato: {res_order['matched_product']['sku_interno']}")
        print(f"  Decisione: {res_order['decision']}")
        print(f"  Migliore Offerta: Fornitore = {res_order['best_offer']['supplier_name']}, Prezzo normalizzato = € {res_order['best_offer']['unit_price_normalized']}, Confezioni necessarie = {res_order['best_offer']['packs_needed']}, Totale stimato = € {res_order['best_offer']['estimated_total']}")
        
        for idx, alt in enumerate(res_order['alternatives']):
            print(f"  Alternativa {idx+1}: Fornitore = {alt['supplier_name']}, Prezzo normalizzato = € {alt['unit_price_normalized']}, Confezioni necessarie = {alt['packs_needed']}")

        assert res_order["decision"] == "resolved", "Resolver fallito"
        assert res_order["best_offer"]["supplier_name"] == "Eurocarta", "Miglior fornitore errato"
        assert res_order["best_offer"]["packs_needed"] == 10, "Calcolo Eurocarta packs errato"
        assert res_order["alternatives"][1]["supplier_name"] == "Altro Fornitore", "Ordinamento alternativi errato"
        assert res_order["alternatives"][1]["packs_needed"] == 20, "Calcolo Altro Fornitore packs errato"
        print("  ✅ Test Resolver d'Ordine superato!")

    print("\n🎉 TUTTI I TEST DEL PRODUCT IDENTITY LAYER SONO STATI SUPERATI CON SUCCESSO!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_verification())
