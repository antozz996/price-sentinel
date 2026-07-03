import asyncio
from decimal import Decimal
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.utenti import Utente
from app.models.fatture import Fattura, RigaFattura, StatoMatching, TipoDocumento
from app.models.listino import ListinoMaster, PFATipo
from app.api.v1.accordi import list_accordi_commerciali
from app.api.v1.fatture import list_righe_fattura

async def run_verification():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Verification of Commercial Agreements")
    print("=" * 60)

    async with async_session_factory() as db:
        # Retrieve the seed admin user
        admin = (await db.execute(select(Utente).where(Utente.email == "admin@pricesentinel.it"))).scalar_one()

        # Let's insert a mock invoice to check purchase accumulations
        # Supplier 1: Drinks & Spirits Srl (ID 1)
        # Location 1: Lido Playa Luna (ID 1)
        invoice = Fattura(
            xml_raw_id=1,
            fornitore_id=1,
            location_id=1,
            numero_documento="TEST-ACCORDI-01",
            data_documento=date(2025, 6, 1),
            data_ricezione_sdi=date(2025, 6, 2),
            tipo_documento=TipoDocumento.TD01,
            totale_imponibile=Decimal("200.00"),
        )
        db.add(invoice)
        await db.flush()

        # Add lines for Gin Hendricks (SKU: GIN-HENDRICKS-70CL)
        # Seed price list has: prezzo_pattuito=22.50, pfa_tipo=percentuale, pfa_valore=0.02 (2%)
        # Let's add an invoice line with 10 units at price 22.50
        line1 = RigaFattura(
            fattura_id=invoice.id,
            numero_linea=1,
            codice_fornitore_raw="DS-GH70",
            descrizione_fornitore_raw="Gin Hendrick's 70cl",
            sku_interno="GIN-HENDRICKS-70CL",
            prezzo_unitario_fatturato=Decimal("22.50"),
            sconto_percentuale=Decimal("0"),
            prezzo_netto_normalizzato=Decimal("22.50"),
            quantita=Decimal("10.00"),
            unita_misura_fattura="Pz",
            aliquota_iva=Decimal("22"),
            is_omaggio=False,
            stato_matching=StatoMatching.matched,
        )

        # Add lines for Rum Diplomatico (SKU: RUM-DIPLOMATICO-70CL)
        # Seed price list has: prezzo_pattuito=32.00, pfa_tipo=fisso, pfa_valore=1.50 (1.50€ per unit)
        # Let's add an invoice line with 5 units at price 32.00
        line2 = RigaFattura(
            fattura_id=invoice.id,
            numero_linea=2,
            codice_fornitore_raw="DS-RD70",
            descrizione_fornitore_raw="Rum Diplomatico Reserva Exclusiva 70cl",
            sku_interno="RUM-DIPLOMATICO-70CL",
            prezzo_unitario_fatturato=Decimal("32.00"),
            sconto_percentuale=Decimal("0"),
            prezzo_netto_normalizzato=Decimal("32.00"),
            quantita=Decimal("5.00"),
            unita_misura_fattura="Pz",
            aliquota_iva=Decimal("22"),
            is_omaggio=False,
            stato_matching=StatoMatching.matched,
        )
        db.add_all([line1, line2])
        await db.flush()

        # Let's simulate a credit note (TD04) returning 2 bottles of Gin Hendricks
        credit_note = Fattura(
            xml_raw_id=1,
            fornitore_id=1,
            location_id=1,
            numero_documento="TEST-NC-01",
            data_documento=date(2025, 6, 10),
            data_ricezione_sdi=date(2025, 6, 11),
            tipo_documento=TipoDocumento.TD04,
            totale_imponibile=Decimal("45.00"),
        )
        db.add(credit_note)
        await db.flush()

        cn_line = RigaFattura(
            fattura_id=credit_note.id,
            numero_linea=1,
            codice_fornitore_raw="DS-GH70",
            descrizione_fornitore_raw="Gin Hendrick's 70cl",
            sku_interno="GIN-HENDRICKS-70CL",
            prezzo_unitario_fatturato=Decimal("22.50"),
            sconto_percentuale=Decimal("0"),
            prezzo_netto_normalizzato=Decimal("22.50"),
            quantita=Decimal("2.00"),
            unita_misura_fattura="Pz",
            aliquota_iva=Decimal("22"),
            is_omaggio=False,
            stato_matching=StatoMatching.matched,
        )
        db.add(cn_line)
        await db.flush()

        print("\n🔍 Testing list_righe_fattura endpoint detail...")
        righe_response = await list_righe_fattura(fattura_id=invoice.id, current_user=admin, db=db)
        for r in righe_response:
            print(f"  Line #{r.numero_linea} | SKU: {r.sku_interno}")
            print(f"    - Invoice Price Paid: € {r.prezzo_netto_normalizzato:.2f}")
            print(f"    - PFA Type:           {r.pfa_tipo} (Value: {r.pfa_valore})")
            netto_str = f"€ {r.netto_rientro:.2f}" if r.netto_rientro is not None else "—"
            print(f"    - Net after Rebate:   {netto_str}")
            
            # Assertions
            if r.sku_interno == "GIN-HENDRICKS-70CL":
                assert r.pfa_tipo == "percentuale"
                assert r.pfa_valore == Decimal("0.0200")
                # 22.50 * (1 - 0.02) = 22.05
                assert r.netto_rientro == Decimal("22.05")
            elif r.sku_interno == "RUM-DIPLOMATICO-70CL":
                assert r.pfa_tipo == "fisso"
                assert r.pfa_valore == Decimal("1.5000")
                # 32.00 - 1.50 = 30.50
                assert r.netto_rientro == Decimal("30.50")

        print("  ✅ list_righe_fattura PFA details are correct!")

        print("\n🔍 Testing list_accordi_commerciali statistics endpoint...")
        accordi_response = await list_accordi_commerciali(current_user=admin, db=db)
        
        # Verify stats for Gin Hendrick's
        # Total purchased qty = 6 (E2E test) + 10 (invoice) - 2 (credit note) = 14 PZ
        # Total spent = 135.00 (E2E test) + 225.00 (invoice) - 45.00 (credit note) = 315.00 €
        # Accrued Rebate (2% of 315.00) = 6.30 €
        # Net unit price weighted average = (315.00 - 6.30) / 14 = 308.70 / 14 = 22.05 €
        gin_acc = next(ac for ac in accordi_response if ac.sku_interno == "GIN-HENDRICKS-70CL")
        print(f"  GIN stats:")
        print(f"    - Total volume:     {gin_acc.quantita_acquistata} Pz")
        print(f"    - Total spent:      € {gin_acc.totale_fatturato:.2f}")
        print(f"    - Accrued Rebate:   € {gin_acc.rientro_accumulato:.2f}")
        print(f"    - Net Average Unit: € {gin_acc.netto_rientro_medio:.2f}")
        assert gin_acc.quantita_acquistata == Decimal("14.0000")
        assert gin_acc.totale_fatturato == Decimal("315.0000")
        assert gin_acc.rientro_accumulato == Decimal("6.3000")
        assert gin_acc.netto_rientro_medio == Decimal("22.0500")

        # Verify stats for Rum Diplomatico
        # Total purchased qty = 3 (E2E test) + 5 (invoice) = 8 PZ
        # Total spent = 97.20 (E2E test) + 160.00 (invoice) = 257.20 €
        # Accrued Rebate (1.50 * 8) = 12.00 €
        # Net unit price weighted average = (257.20 - 12.00) / 8 = 245.20 / 8 = 30.65 €
        rum_acc = next(ac for ac in accordi_response if ac.sku_interno == "RUM-DIPLOMATICO-70CL")
        print(f"  RUM stats:")
        print(f"    - Total volume:     {rum_acc.quantita_acquistata} Pz")
        print(f"    - Total spent:      € {rum_acc.totale_fatturato:.2f}")
        print(f"    - Accrued Rebate:   € {rum_acc.rientro_accumulato:.2f}")
        print(f"    - Net Average Unit: € {rum_acc.netto_rientro_medio:.2f}")
        assert rum_acc.quantita_acquistata == Decimal("8.0000")
        assert rum_acc.totale_fatturato == Decimal("257.2000")
        assert rum_acc.rientro_accumulato == Decimal("12.0000")
        assert rum_acc.netto_rientro_medio == Decimal("30.6500")

        print("  ✅ list_accordi_commerciali stats are correct!")
        await db.rollback() # Rollback mock invoice/credit note data

    print("\n🎉 ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_verification())
