import asyncio
import argparse
from decimal import Decimal
from datetime import date
from datetime import datetime
from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price

BEER_BATCH_1_CONFIG = [
    {
        "supplier_code": "NAVAS_BIR0005",
        "sku": "BEER-CERES-33CL-BT",
        "canonical_name": "Ceres 33 cl bottiglia",
        "brand": "Ceres",
        "category": "beer",
        "volume_ml": 330,
        "pack_qty": 24,
        "container_type": "glass_bottle",
        "comparison_unit": "liter",
        "price": Decimal("28.69"),
        "raw_desc": "BIRRA CERES 33 CL X 24 BT",
        "normalized_desc": "birra ceres 33 centilitro 24 pezzi bottiglia"
    },
    {
        "supplier_code": "NAVAS_BIR0009",
        "sku": "BEER-CORONA_EXTRA-33CL-BT",
        "canonical_name": "Corona Extra 33 cl bottiglia",
        "brand": "Corona",
        "category": "beer",
        "volume_ml": 330,
        "pack_qty": 24,
        "container_type": "glass_bottle",
        "comparison_unit": "liter",
        "price": Decimal("22.95"),
        "raw_desc": "BIRRA CORONA 33 CL X 24 BT",
        "normalized_desc": "birra corona 33 centilitro 24 pezzi bottiglia"
    }
]

async def run_batch(apply: bool):
    supplier_id = 11  # Navas Srl
    today = date.today()
    
    print("=" * 70)
    print(f"🍺 NAVAS BEER BATCH 1 - {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 70)
    
    async with async_session_factory() as db:
        # Conteggi prima
        async with db.begin():
            prod_count_before = (await db.execute(select(func.count(Product.id)))).scalar()
            alias_count_before = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            price_count_before = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id, ListinoMaster.data_scadenza.is_(None)))).scalar()
            
        print("\n📊 CONTEGGI DB PRE-OPERAZIONE:")
        print(f"  Prodotti Canonici Totali: {prod_count_before}")
        print(f"  Alias Navas Totali:        {alias_count_before}")
        print(f"  Prezzi Navas Attivi:       {price_count_before}")
        print("-" * 50)
        
        products_created = 0
        aliases_created = 0
        prices_created = 0
        
        async with db.begin():
            for conf in BEER_BATCH_1_CONFIG:
                # 1. Verifica/Crea Prodotto Canonico
                p_stmt = select(Product).where(Product.sku_interno == conf["sku"])
                prod = (await db.execute(p_stmt)).scalars().first()
                
                if not prod:
                    if apply:
                        prod = Product(
                            sku_interno=conf["sku"],
                            canonical_name=conf["canonical_name"],
                            normalized_name=conf["canonical_name"].lower(),
                            brand=conf["brand"],
                            category=conf["category"],
                            volume_ml=conf["volume_ml"],
                            unit_count=1,
                            container_type=conf["container_type"],
                            comparison_unit=conf["comparison_unit"],
                            is_active=True
                        )
                        db.add(prod)
                        # Flush to generate ID
                        await db.flush()
                        print(f"➕ [PRODOTTO] Creato: {conf['sku']} -> {conf['canonical_name']}")
                    else:
                        print(f"🔍 [PRODOTTO] Da Creare: {conf['sku']} -> {conf['canonical_name']}")
                    products_created += 1
                else:
                    print(f"✓ [PRODOTTO] Già Esistente: {conf['sku']}")
                
                # 2. Verifica/Crea SupplierProductAlias
                a_stmt = select(SupplierProductAlias).where(
                    SupplierProductAlias.supplier_id == supplier_id,
                    SupplierProductAlias.supplier_code == conf["supplier_code"]
                )
                alias = (await db.execute(a_stmt)).scalars().first()
                
                if not alias:
                    if apply:
                        alias = SupplierProductAlias(
                            supplier_id=supplier_id,
                            product_id=prod.id,
                            supplier_code=conf["supplier_code"],
                            raw_description=conf["raw_desc"],
                            normalized_description=conf["normalized_desc"],
                            pack_qty=conf["pack_qty"],
                            volume_ml=conf["volume_ml"],
                            status="approved",
                            confidence_score=100.0,
                            source="manual_approval_beers"
                        )
                        db.add(alias)
                        await db.flush()
                        print(f"➕ [ALIAS] Creato: {conf['supplier_code']} -> {conf['raw_desc']}")
                    else:
                        print(f"🔍 [ALIAS] Da Creare: {conf['supplier_code']} -> {conf['raw_desc']}")
                    aliases_created += 1
                else:
                    print(f"✓ [ALIAS] Già Esistente: {conf['supplier_code']}")
                    if apply and alias.product_id != prod.id:
                        alias.product_id = prod.id
                        alias.status = "approved"
                        db.add(alias)
                        print(f"⚡ [ALIAS] Ricollegato all'ID Prodotto {prod.id}")
                
                # 3. Salva in ListinoMaster (usando logica alias-aware)
                if apply:
                    outcome = await save_append_only_price(
                        db=db,
                        fornitore_id=supplier_id,
                        sku_interno=conf["sku"],
                        descrizione=conf["raw_desc"],
                        prezzo_pattuito=conf["price"],
                        unita_misura="piece",
                        data_inizio=today,
                        supplier_product_alias_id=alias.id
                    )
                    print(f"➕ [PREZZO] Esito: {outcome} per SKU {conf['sku']} (prezzo pack: € {conf['price']})")
                    if outcome in ("created", "updated"):
                        prices_created += 1
                else:
                    # Calcola prezzo normalizzato stimato
                    vol_litri = Decimal(str(conf["volume_ml"])) / Decimal("1000")
                    prezzo_norm = conf["price"] / (Decimal(str(conf["pack_qty"])) * vol_litri)
                    print(f"🔍 [PREZZO] Da Creare: SKU {conf['sku']} | Prezzo Pack: € {conf['price']} | Normalizzato: € {prezzo_norm:.4f} / L")
                    prices_created += 1
                    
                # 4. Se esiste un MatchCandidate pendente per questa descrizione/codice, lo risolve
                mc_stmt = select(MatchCandidate).where(
                    MatchCandidate.supplier_id == supplier_id,
                    MatchCandidate.raw_description == conf["raw_desc"],
                    MatchCandidate.status == "pending"
                )
                mc = (await db.execute(mc_stmt)).scalars().first()
                if mc:
                    if apply:
                        mc.status = "resolved"
                        mc.resolved_at = datetime.utcnow()
                        db.add(mc)
                        print(f"⚡ [CANDIDATO] MatchCandidate risolto per '{conf['raw_desc']}'")
                    else:
                        print(f"🔍 [CANDIDATO] MatchCandidate pendente verrà risolto per '{conf['raw_desc']}'")
            
            # Se siamo in Dry Run, la transazione andrà in ROLLBACK automatico alla fine del blocco
            if not apply:
                print("\n⚠️ MODALITÀ DRY RUN: Nessun dato è stato salvato nel database (ROLLBACK).")
            else:
                print("\n✅ MODALITÀ APPLY: Dati salvati con successo (COMMIT).")
                
        # Conteggi simulati/dopo
        prod_count_after = prod_count_before + (products_created if not apply or apply else 0) # visualizzazione logica
        alias_count_after = alias_count_before + (aliases_created if not apply or apply else 0)
        
        # Nel caso reale ricalcoliamo a fine transazione
        if apply:
            async with async_session_factory() as db_after:
                async with db_after.begin():
                    prod_count_after = (await db_after.execute(select(func.count(Product.id)))).scalar()
                    alias_count_after = (await db_after.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
                    price_count_after = (await db_after.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id, ListinoMaster.data_scadenza.is_(None)))).scalar()
        else:
            prod_count_after = prod_count_before + products_created
            alias_count_after = alias_count_before + aliases_created
            price_count_after = price_count_before + prices_created
            
        print("\n📊 CONTEGGI DB POST-OPERAZIONE:")
        print(f"  Prodotti Canonici Totali: {prod_count_after} (Variazione: +{prod_count_after - prod_count_before})")
        print(f"  Alias Navas Totali:        {alias_count_after} (Variazione: +{alias_count_after - alias_count_before})")
        print(f"  Prezzi Navas Attivi:       {price_count_after} (Variazione: +{price_count_after - price_count_before})")
        print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approve and import clean Navas beers")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Simulate import process")
    group.add_argument("--apply", action="store_true", help="Execute real database changes")
    
    args = parser.parse_args()
    asyncio.run(run_batch(apply=args.apply))
