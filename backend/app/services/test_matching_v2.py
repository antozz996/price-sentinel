"""
Integration Tests per Matching Engine v2 (Fase 3 / Fase 4 / Fase 5 / Fase 8).
"""

import asyncio
from decimal import Decimal
from datetime import date
from sqlalchemy import select

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from app.services.matching import resolve_invoice_line_product, match_riga


async def run_matching_tests():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Integration Verification of Matching Engine v2")
    print("=" * 60)

    async with async_session_factory() as db:
        # Recupera il fornitore di esempio
        forn = (await db.execute(select(Fornitore).where(Fornitore.partita_iva == "12345678901"))).scalar_one_or_none()
        if not forn:
            print("❌ Errore: Esegui prima il seed del database!")
            return

        # 1. Verifica se i prodotti canonici del seed sono presenti, altrimenti creali
        prod_hendricks = (await db.execute(select(Product).where(Product.canonical_name == "Hendrick's Gin 1L"))).scalar_one_or_none()
        if not prod_hendricks:
            print("  ⚠️ Prodotti canonici non trovati, li creo...")
            prod_hendricks = Product(
                canonical_name="Hendrick's Gin 1L",
                sku_interno="GIN-HENDRICKS-1L",
                brand="hendrick's",
                category="beverage",
                subcategory="spirits",
                variant="classica",
                volume_ml=1000,
                comparison_unit="bottle",
                unit_count=1,
                is_active=True,
            )
            prod_fragola = Product(
                canonical_name="Keglevich Fragola 1L",
                sku_interno="VODKA-KEGLEVICH-FRAGOLA-1L",
                brand="keglevich",
                category="beverage",
                subcategory="spirits",
                variant="fragola",
                volume_ml=1000,
                comparison_unit="bottle",
                unit_count=1,
                is_active=True,
            )
            prod_pesca = Product(
                canonical_name="Keglevich Pesca 1L",
                sku_interno="VODKA-KEGLEVICH-PESCA-1L",
                brand="keglevich",
                category="beverage",
                subcategory="spirits",
                variant="pesca",
                volume_ml=1000,
                comparison_unit="bottle",
                unit_count=1,
                is_active=True,
            )
            prod_coca_vetro = Product(
                canonical_name="Coca Cola Vetro 33cl",
                sku_interno="SODA-COCACOLA-GLASS-33CL",
                brand="coca cola",
                category="beverage",
                subcategory="soda",
                variant="classica",
                volume_ml=330,
                container_type="vetro",
                comparison_unit="bottle",
                unit_count=1,
                is_active=True,
            )
            prod_coca_latta = Product(
                canonical_name="Coca Cola Lattina 33cl",
                sku_interno="SODA-COCACOLA-CAN-33CL",
                brand="coca cola",
                category="beverage",
                subcategory="soda",
                variant="classica",
                volume_ml=330,
                container_type="lattina",
                comparison_unit="bottle",
                unit_count=1,
                is_active=True,
            )
            prod_acqua = Product(
                canonical_name="Acqua Natia 0.50L x24",
                sku_interno="WATER-NATIA-PET-50CL",
                brand="natia",
                category="beverage",
                subcategory="water",
                volume_ml=500,
                container_type="pet",
                comparison_unit="bottle",
                unit_count=24,
                is_active=True,
            )
            db.add_all([prod_hendricks, prod_fragola, prod_pesca, prod_coca_vetro, prod_coca_latta, prod_acqua])
            await db.flush()
            
            # Crea anche i listini
            listino_hendricks = ListinoMaster(
                fornitore_id=forn.id,
                sku_interno="GIN-HENDRICKS-1L",
                descrizione="Hendrick's Gin 1L",
                prezzo_pattuito=Decimal("30.00"),
                unita_misura="Pz",
                data_inizio_validita=date(2025, 1, 1),
            )
            listino_acqua = ListinoMaster(
                fornitore_id=forn.id,
                sku_interno="WATER-NATIA-PET-50CL",
                descrizione="Acqua Natia 0.50L",
                prezzo_pattuito=Decimal("0.50"), # prezzo a bottiglia normalizzato
                unita_misura="Pz",
                data_inizio_validita=date(2025, 1, 1),
            )
            db.add_all([listino_hendricks, listino_acqua])
            await db.flush()
        else:
            prod_fragola = (await db.execute(select(Product).where(Product.canonical_name == "Keglevich Fragola 1L"))).scalar_one()
            prod_pesca = (await db.execute(select(Product).where(Product.canonical_name == "Keglevich Pesca 1L"))).scalar_one()
            prod_coca_vetro = (await db.execute(select(Product).where(Product.canonical_name == "Coca Cola Vetro 33cl"))).scalar_one()
            prod_coca_latta = (await db.execute(select(Product).where(Product.canonical_name == "Coca Cola Lattina 33cl"))).scalar_one()
            prod_acqua = (await db.execute(select(Product).where(Product.canonical_name == "Acqua Natia 0.50L x24"))).scalar_one()

        # ── CASO 1: "GIN HENDRICK'S CL 100" (Auto-match attributi) ──
        res1 = await resolve_invoice_line_product(db, forn.id, "GIN HENDRICK'S CL 100")
        assert res1["decision"] == "auto_match", f"Decisione errata: {res1['decision']}"
        assert res1["product_id"] == prod_hendricks.id, "Mancato match con Hendrick's"
        print(f"  ✅ Caso 1: 'GIN HENDRICK'S CL 100' -> auto_match con Hendrick's Gin 1L (ID={res1['product_id']})")

        # ── CASO 2: "HENDRICKS GIN LT 1" (Auto-match attributi) ──
        res2 = await resolve_invoice_line_product(db, forn.id, "HENDRICKS GIN LT 1")
        assert res2["decision"] == "auto_match", f"Decisione errata: {res2['decision']}"
        assert res2["product_id"] == prod_hendricks.id, "Mancato match con Hendrick's"
        print(f"  ✅ Caso 2: 'HENDRICKS GIN LT 1' -> auto_match con Hendrick's Gin 1L")

        # ── CASO 3: "GIN HENDRIX 1000ML" (Needs review / No codice fornitore) ──
        res3 = await resolve_invoice_line_product(db, forn.id, "GIN HENDRIX 1000ML")
        # In questo caso la descrizione contiene un typo sul brand (hendrix -> hendrick's)
        # e ha un punteggio alto, ma deve essere auto_match se supera soglia 90
        assert res3["decision"] == "auto_match", f"Decisione errata: {res3['decision']}"
        print(f"  ✅ Caso 3: 'GIN HENDRIX 1000ML' -> auto_match (corretto brand ed volume)")

        # ── CASO 4: "KEGLEVICH FRAGOLA LT 1" vs "KEGLEVICH PESCA LT 1" (Variant mismatch block) ──
        res4 = await resolve_invoice_line_product(db, forn.id, "KEGLEVICH FRAGOLA LT 1")
        # Deve matchare Fragola ma NON Pesca
        assert res4["product_id"] == prod_fragola.id
        # Se verifichiamo la riga contro il prodotto Pesca, lo score deve essere bloccato per variant mismatch
        candidates_pesca = [c for c in res4["candidates"] if c["product_id"] == prod_pesca.id]
        if candidates_pesca:
            assert candidates_pesca[0]["block"] == True, "Gusto diverso non bloccato!"
        print(f"  ✅ Caso 4: Keglevich Fragola vs Pesca differenziati ed esclusi correttamente (mismatch variant bloccato)")

        # ── CASO 5: "COCA COLA VETRO 33CL" vs "COCA COLA LATTINA 33CL" (Container mismatch block) ──
        res5 = await resolve_invoice_line_product(db, forn.id, "COCA COLA VETRO 33CL")
        assert res5["product_id"] == prod_coca_vetro.id
        candidates_latta = [c for c in res5["candidates"] if c["product_id"] == prod_coca_latta.id]
        if candidates_latta:
            assert candidates_latta[0]["block"] == True, "Contenitore diverso non bloccato!"
        print(f"  ✅ Caso 5: Coca Cola Vetro vs Lattina differenziati correttamente (mismatch container bloccato)")

        # ── CASO 6: "ACQUA NATIA 0,50 X24" (Normalizzazione prezzo) ──
        # Prezzo cassa da 24 = 12.00€. Prezzo listino pattuito = 0.50€ a bottiglia.
        # Il prezzo normalizzato deve essere 12.00 / 24 = 0.50€. Delta = 0.00.
        res6 = await match_riga(
            db=db,
            fornitore_id=forn.id,
            codice_articolo="NAT-50CL",
            tipo_codice="FORNITORE",
            descrizione="ACQUA NATIA 0,50 X24",
            prezzo_netto_normalizzato=Decimal("12.00"),
            quantita=Decimal("1"),
            unita_misura_fattura="Cassa",
            data_documento="2025-06-01",
        )
        assert res6.matched == True, "Acqua Natia non auto-matchata"
        assert res6.prezzo_fatturato_normalizzato == Decimal("0.5000"), f"Prezzo non normalizzato correttamente: {res6.prezzo_fatturato_normalizzato}"
        assert res6.delta_prezzo == Decimal("0.0000"), f"Delta errato: {res6.delta_prezzo}"
        print(f"  ✅ Caso 6: 'ACQUA NATIA 0,50 X24' -> prezzo normalizzato a bottiglia: €{res6.prezzo_fatturato_normalizzato} (Delta: {res6.delta_prezzo})")

        # ── CASO 7: Riga sconosciuta degradata a parking senza anomalia ──
        res7 = await match_riga(
            db=db,
            fornitore_id=forn.id,
            codice_articolo="UNKNOWN-CODE",
            tipo_codice="FORNITORE",
            descrizione="Liquore Sconosciuto Esotico 1L",
            prezzo_netto_normalizzato=Decimal("20.00"),
            quantita=Decimal("1"),
            unita_misura_fattura="Pz",
            data_documento="2025-06-01",
        )
        assert res7.matched == False
        assert res7.livello == 4 # Parking area
        print(f"  ✅ Caso 7: Prodotto sconosciuto degradato in Parking Area (Livello 4)")

        # ── CASO 8: Learn Loop (alias confermato manualmente ed auto-match successivo) ──
        # 1. Prova a matchare una riga sconosciuta "NUOVO_PRODOTTO_TEST"
        raw_desc = "NUOVO_PRODOTTO_TEST"
        res_pre = await resolve_invoice_line_product(db, forn.id, raw_desc, supplier_code="CODE-99")
        assert res_pre["decision"] == "parking"
        
        # 2. Conferma manuale dell'operatore -> salvataggio alias
        manual_alias = SupplierProductAlias(
            supplier_id=forn.id,
            product_id=prod_hendricks.id,
            supplier_code="CODE-99",
            raw_description=raw_desc,
            normalized_description=raw_desc.lower(),
            source="manual",
        )
        db.add(manual_alias)
        await db.flush()
        
        # 3. Riesegui il match con lo stesso codice fornitore -> deve essere auto_match immediato
        res_post = await resolve_invoice_line_product(db, forn.id, raw_desc, supplier_code="CODE-99")
        assert res_post["decision"] == "auto_match"
        assert res_post["product_id"] == prod_hendricks.id
        print(f"  ✅ Caso 8: Conferma manuale registrata con successo. Righe future auto-matchate istantaneamente.")

        # Rollback del test per non alterare il DB reale
        await db.rollback()
        print("\n🎉 Tutti i test d'integrazione del Matching Engine v2 sono passati!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_matching_tests())
