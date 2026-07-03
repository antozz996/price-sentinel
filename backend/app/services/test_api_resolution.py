"""
Unit Tests per l'API di Risoluzione delle Righe Parcheggiate (Fase 6 / 8).
"""

import asyncio
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.fatture import RigaFattura, Fattura, StatoMatching, TipoDocumento, XMLRaw, StatoIngestion, SourceIngestion
from app.models.anomalie import Anomalia
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from app.api.v1.fatture import resolve_parked_line, ResolveActionPayload, list_riga_candidates


async def run_api_tests():
    print("=" * 60)
    print("🧪 PRICE SENTINEL — Verification of Parking Area Resolution APIs")
    print("=" * 60)

    async with async_session_factory() as db:
        # Recupera il fornitore e la location di esempio
        forn = (await db.execute(select(Fornitore).where(Fornitore.partita_iva == "12345678901"))).scalar_one_or_none()
        if not forn:
            print("❌ Errore: Esegui prima il seed del database!")
            return

        # Crea un prodotto canonico di test
        test_prod = Product(
            canonical_name="Limoncello di Sorrento 1L",
            sku_interno="LIQ-LIMONCELLO-1L",
            brand="sorrento",
            category="beverage",
            subcategory="spirits",
            volume_ml=1000,
            comparison_unit="bottle",
            is_active=True,
        )
        db.add(test_prod)
        await db.flush()

        # Aggiungi listino master di test
        listino = ListinoMaster(
            fornitore_id=forn.id,
            sku_interno="LIQ-LIMONCELLO-1L",
            descrizione="Limoncello 1L",
            prezzo_pattuito=Decimal("12.00"),
            unita_misura="Pz",
            data_inizio_validita=date(2025, 1, 1),
        )
        db.add(listino)
        await db.flush()

        # Crea XMLRaw di test per superare il vincolo di foreign key
        mock_xml = XMLRaw(
            payload="<xml></xml>",
            nome_file="test_resolve.xml",
            hash_idempotenza="hash_resolve_test_unique_123",
            source=SourceIngestion.upload_manuale,
            stato_ingestion=StatoIngestion.parsato,
            data_ricezione=datetime.utcnow(),
        )
        db.add(mock_xml)
        await db.flush()

        # Crea una fattura e una riga in parking
        test_invoice = Fattura(
            xml_raw_id=mock_xml.id,
            fornitore_id=forn.id,
            location_id=1,
            numero_documento="API-TEST-INV-1",
            data_documento=date(2025, 6, 15),
            data_ricezione_sdi=date(2025, 6, 16),
            tipo_documento=TipoDocumento.TD01,
            totale_imponibile=Decimal("15.00"),
        )
        db.add(test_invoice)
        await db.flush()

        test_line = RigaFattura(
            fattura_id=test_invoice.id,
            numero_linea=1,
            codice_fornitore_raw="FORN-LIM-100",
            descrizione_fornitore_raw="SORRENTO LIMONCELLO LT 1",
            prezzo_unitario_fatturato=Decimal("15.00"), # Prezzo aumentato (15.00 > 12.00)
            sconto_percentuale=Decimal("0"),
            prezzo_netto_normalizzato=Decimal("15.00"),
            quantita=Decimal("1"),
            unita_misura_fattura="Pz",
            stato_matching=StatoMatching.in_parking,
        )
        db.add(test_line)
        await db.flush()

        # Aggiungi candidati mock
        candidate = MatchCandidate(
            invoice_line_id=test_line.id,
            product_id=test_prod.id,
            score=Decimal("85.00"),
            reason_json={"note": "Test candidate"},
        )
        db.add(candidate)
        await db.flush()

        # ── TEST 1: Recupera candidati ──
        cands = await list_riga_candidates(riga_id=test_line.id, db=db)
        assert len(cands) == 1
        assert cands[0]["product_id"] == test_prod.id
        print("  ✅ Test 1 Superato: Candidati recuperati con successo via API")

        # ── TEST 2: Esegui Associazione a Prodotto Esistente (con rincaro) ──
        payload = ResolveActionPayload(
            action="associate_existing",
            product_id=test_prod.id,
        )
        res = await resolve_parked_line(riga_id=test_line.id, payload=payload, db=db)
        assert res["status"] == "success"

        # Ricarica riga ed alias per verificare lo stato
        await db.refresh(test_line)
        assert test_line.stato_matching == StatoMatching.matched
        assert test_line.sku_interno == "LIQ-LIMONCELLO-1L"

        alias_res = await db.execute(
            select(SupplierProductAlias).where(
                SupplierProductAlias.supplier_code == "FORN-LIM-100"
            )
        )
        alias = alias_res.scalar_one_or_none()
        assert alias is not None
        assert alias.product_id == test_prod.id
        print("  ✅ Test 2 Superato: Associazione manuale corretta (stato riga aggiornato ed alias creato)")

        # ── TEST 3: Verifica se è stata creata l'Anomalia per il rincaro ──
        anomalia_res = await db.execute(
            select(Anomalia).where(Anomalia.riga_fattura_id == test_line.id)
        )
        anomalia = anomalia_res.scalar_one_or_none()
        assert anomalia is not None
        assert anomalia.delta_prezzo == Decimal("3.0000") # 15.00 - 12.00
        print(f"  ✅ Test 3 Superato: Anomalia di rincaro rilevata corretta (Delta: €{anomalia.delta_prezzo})")

        # ── TEST 4: Esegui azione 'mark_free' (Omaggio) ──
        # Ripristina riga in parking per testare
        test_line.stato_matching = StatoMatching.in_parking
        await db.flush()

        payload_free = ResolveActionPayload(action="mark_free")
        res_free = await resolve_parked_line(riga_id=test_line.id, payload=payload_free, db=db)
        assert res_free["status"] == "success"

        await db.refresh(test_line)
        assert test_line.is_omaggio == True
        assert test_line.stato_matching == StatoMatching.matched

        # L'anomalia precedente deve essere stata rimossa
        anomalia_free = (await db.execute(
            select(Anomalia).where(Anomalia.riga_fattura_id == test_line.id)
        )).scalar_one_or_none()
        assert anomalia_free is None
        print("  ✅ Test 4 Superato: Riga marcata come omaggio e anomalia correttamente eliminata")

        # Rollback per non sporcare il DB reale
        await db.rollback()
        print("\n🎉 Tutti i test delle API di Risoluzione del Parking Area sono passati!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_api_tests())
