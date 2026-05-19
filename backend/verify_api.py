import asyncio
import sys
from decimal import Decimal
from datetime import date, datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

# Add backend directory to Python path
sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory
from app.models.anomalie import Anomalia, StatoValidazione, NotaDiCredito, ApprovazionePrezzo
from app.models.listino import ListinoMaster
from app.models.alias import AliasProdotto
from app.models.fatture import RigaFattura, Fattura, StatoMatching, TipoDocumento
from app.services.matching import match_riga
from app.services.ingestion import _process_td04
from app.api.v1.intelligence import create_approvazione
from app.schemas.approvazioni import ApprovazionePrezzoCreate

class DummyObject:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

async def test_all():
    print("🚀 Starting Sprint 4 E2E Verification Suite...")
    
    async with async_session_factory() as session:
        # 1. Verify GIN Indexes and trigram capabilities
        print("\n🔍 1. Verifying Database Indices & pg_trgm extension...")
        idx_res = await session.execute(text("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'listino_master' AND indexname = 'idx_listino_master_trgm';
        """))
        idx_exists = idx_res.scalar()
        if idx_exists:
            print(" ✅ idx_listino_master_trgm GIN index exists!")
        else:
            print(" ⚠️ idx_listino_master_trgm GIN index not found (using default mock fallback).")

        # 2. Verify Alias custom scale factors & match_riga division logic
        print("\n📏 2. Verifying Custom Alias Scale Factors & Matching Division...")
        # Create a test alias
        test_alias = AliasProdotto(
            fornitore_id=1,
            codice_fornitore_originale="SCALE_TEST_1",
            sku_interno="SKU_TEST_1",
            coefficiente_conversione=Decimal("6.0"),
            created_at=datetime.now(timezone.utc)
        )
        session.add(test_alias)
        
        # Create corresponding baseline listino
        test_listino = ListinoMaster(
            fornitore_id=1,
            sku_interno="SKU_TEST_1",
            descrizione="Prodotto Test Scaling",
            prezzo_pattuito=Decimal("2.00"),
            unita_misura="Kg",
            data_inizio_validita=date.today(),
            data_scadenza=None
        )
        session.add(test_listino)
        await session.flush()

        # Run match_riga simulation
        # Invoice price is 12.00 (which for 6 units equals 2.00 baseline price)
        result = await match_riga(
            db=session,
            fornitore_id=1,
            codice_articolo="SCALE_TEST_1",
            tipo_codice="CODE",
            descrizione="Prodotto Test Scaling",
            prezzo_netto_normalizzato=Decimal("12.00"),
            quantita=Decimal("1.0"),
            unita_misura_fattura="Box6",
            data_documento=date.today()
        )
        
        print(f" -> Level Match: {result.livello}")
        print(f" -> Internal SKU: {result.sku_interno}")
        print(f" -> Normalized Invoice Price: {result.prezzo_fatturato_normalizzato}")
        print(f" -> Baseline Listino Price: {result.prezzo_listino}")
        print(f" -> UoM Conversion Coefficient: {result.coefficiente_uom}")
        print(f" -> Delta Prezzo: {result.delta_prezzo}")
        print(f" -> Delta Totale: {result.delta_totale}")

        assert result.matched is True
        assert result.coefficiente_uom == Decimal("6.0")
        assert result.delta_prezzo == Decimal("0.0000") # 12.00 / 6.0 = 2.00. Delta = 2.00 - 2.00 = 0
        print(" ✅ Custom scale factor matched & divided correctly!")

        # 3. Verify Automatic Catalog updates on approval
        print("\n📚 3. Verifying Append-Only Catalog Updates on Approval...")
        appr_data = ApprovazionePrezzoCreate(
            sku_interno="SKU_TEST_1",
            descrizione_orig="Prodotto Test Scaling",
            mese=date.today().strftime("%Y-%m"),
            prezzo_approvato=2.50,
            stato="APPROVATO"
        )
        
        # Invoke backend router function
        appr_res = await create_approvazione(
            data=appr_data,
            _admin=True,
            db=session
        )
        await session.flush()
        
        # Query listino master for active and historical records of this SKU
        lst_res = await session.execute(
            select(ListinoMaster)
            .where(ListinoMaster.sku_interno == "SKU_TEST_1")
            .order_by(ListinoMaster.id.asc())
        )
        all_listini = lst_res.scalars().all()
        print(f" -> Total contract records for SKU_TEST_1: {len(all_listini)}")
        for idx, lst in enumerate(all_listini):
            print(f"   [{idx}] Price: {lst.prezzo_pattuito}, Valid From: {lst.data_inizio_validita}, Expired: {lst.data_scadenza}")

        assert len(all_listini) == 2
        assert all_listini[0].data_scadenza == date.today() # Old expired
        assert all_listini[1].prezzo_pattuito == Decimal("2.50") # New active appended
        assert all_listini[1].data_scadenza is None
        print(" ✅ Catalog synchronization is correctly append-only!")

        # 4. Verify TD04 credit note stornos
        print("\n💵 4. Verifying TD04 Credit Note storno reconciliations...")
        # Create a pending anomaly to resolve
        test_fattura_orig = Fattura(
            xml_raw_id=1,
            fornitore_id=1,
            location_id=1,
            numero_documento="FAT_TEST_ORIG",
            data_documento=date.today(),
            data_ricezione_sdi=date.today(),
            tipo_documento=TipoDocumento.TD01,
            totale_imponibile=Decimal("100.00")
        )
        session.add(test_fattura_orig)
        await session.flush()

        test_riga_orig = RigaFattura(
            fattura_id=test_fattura_orig.id,
            numero_linea=1,
            prezzo_unitario_fatturato=Decimal("15.00"),
            codice_fornitore_raw="ITEM_ANOMALY",
            descrizione_fornitore_raw="Prodotto Con Rincaro",
            prezzo_netto_normalizzato=Decimal("15.00"),
            quantita=Decimal("2.0"),
            unita_misura_fattura="Pz",
            stato_matching=StatoMatching.matched,
            sku_interno="SKU_TEST_2"
        )
        session.add(test_riga_orig)
        await session.flush()

        test_anomaly = Anomalia(
            riga_fattura_id=test_riga_orig.id,
            delta_prezzo=Decimal("5.00"),
            delta_totale=Decimal("10.00"),
            prezzo_listino_snapshot=Decimal("10.00"),
            prezzo_fatturato_snapshot=Decimal("15.00"),
            stato_validazione=StatoValidazione.da_verificare
        )
        session.add(test_anomaly)
        await session.flush()

        # Simulate credit note (TD04) parsed items
        parsed_nc_riga = DummyObject(
            numero_linea=1,
            codice_articolo="ITEM_ANOMALY",
            descrizione="Prodotto Con Rincaro",
            prezzo_unitario=Decimal("15.00"),
            sconto_percentuale=Decimal("0.0"),
            prezzo_netto_normalizzato=Decimal("15.00"), # Credit unit price
            quantita=Decimal("2.0"), # Credit quantity
            unita_misura="Pz",
            aliquota_iva=Decimal("22.0"),
            is_omaggio=False
        )
        parsed_nc = DummyObject(
            numero_documento="NC_TEST_RECONCILE",
            data_documento="2026-05-19",
            data_ricezione_sdi="2026-05-19",
            totale_imponibile=Decimal("30.00"),
            righe=[parsed_nc_riga]
        )

        dummy_fornitore = DummyObject(id=1)
        dummy_location = DummyObject(id=1)

        # Execute TD04 ingestion hook
        rec_res = await _process_td04(
            db=session,
            xml_raw_id=2,
            parsed=parsed_nc,
            fornitore=dummy_fornitore,
            location=dummy_location
        )
        await session.flush()
        
        print(f" -> Process TD04 response: {rec_res}")
        
        # Verify if our anomaly has transitioned to 'risolta'
        session.expire(test_anomaly, ['note_di_credito', 'stato_validazione'])
        refreshed_anomaly_res = await session.execute(
            select(Anomalia)
            .options(selectinload(Anomalia.note_di_credito))
            .where(Anomalia.id == test_anomaly.id)
        )
        refreshed_anomaly = refreshed_anomaly_res.scalar_one()
        
        print(f" -> Anomaly Validation Status: {refreshed_anomaly.stato_validazione}")
        print(f" -> Recovered credit note counts: {len(refreshed_anomaly.note_di_credito)}")
        if refreshed_anomaly.note_di_credito:
            print(f" -> Registered NC amount: {refreshed_anomaly.note_di_credito[0].importo_recuperato}")

        assert refreshed_anomaly.stato_validazione == StatoValidazione.risolta
        assert len(refreshed_anomaly.note_di_credito) == 1
        assert refreshed_anomaly.note_di_credito[0].importo_recuperato == 10.00
        print(" ✅ TD04 Credit note stornos & status changes verified successfully!")

        print("\n🚨 Rollback database session to maintain clean state...")
        await session.rollback()
        print("🎉 All Sprint 4 checks completed perfectly! Core pipelines verified.")

if __name__ == "__main__":
    asyncio.run(test_all())
