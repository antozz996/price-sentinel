import asyncio
import argparse
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price

PREMIUM_MIXERS_BATCH_1_CONFIG = [
    {
        "supplier_code": "NAVAS_4242THOMPINK_POMP",
        "sku": "SOFT-THOMAS_HENRY_PINK_GRAPEFRUIT-20CL-BT",
        "canonical_name": "Thomas Henry Pink Grapefruit 20 cl bottiglia",
        "brand": "Thomas Henry",
        "variant": "Pink Grapefruit",
        "volume_ml": 200,
        "pack_qty": 1,
        "price": Decimal("0.8197"),
        "raw_desc": "THOMAS H.PINK POMPELMO 20 CL"
    },
    {
        "supplier_code": "NAVAS_GINGER5",
        "sku": "SOFT-THOMAS_HENRY_GINGER_BEER-20CL-BT",
        "canonical_name": "Thomas Henry Ginger Beer 20 cl bottiglia",
        "brand": "Thomas Henry",
        "variant": "Ginger Beer",
        "volume_ml": 200,
        "pack_qty": 24,
        "price": Decimal("26.3600"),
        "raw_desc": "THOMAS HENRY GINGER BEER 200 X 24"
    },
    {
        "supplier_code": "NAVAS_FEVER0025",
        "sku": "SOFT-FEVER_TREE_ELDERFLOWER-20CL-BT",
        "canonical_name": "Fever-Tree Elderflower Tonic 20 cl bottiglia",
        "brand": "Fever-Tree",
        "variant": "Elderflower Tonic Water",
        "volume_ml": 200,
        "pack_qty": 1,
        "price": Decimal("1.0196"),
        "raw_desc": "FEVER-TREE EDERFLOWER TONIC WATER 200 ML"
    },
    {
        "supplier_code": "NAVAS_FEVER2",
        "sku": "SOFT-FEVER_TREE_INDIAN_TONIC-20CL-BT",
        "canonical_name": "Fever-Tree Indian Tonic 20 cl bottiglia",
        "brand": "Fever-Tree",
        "variant": "Indian Tonic",
        "volume_ml": 200,
        "pack_qty": 1,
        "price": Decimal("1.0165"),
        "raw_desc": "FEVER-TREE TONIC 200  ML INDIAN"
    },
    {
        "supplier_code": "NAVAS_FEVER3",
        "sku": "SOFT-FEVER_TREE_MEDITERRANEAN-20CL-BT",
        "canonical_name": "Fever-Tree Mediterranean Tonic 20 cl bottiglia",
        "brand": "Fever-Tree",
        "variant": "Mediterranean Tonic Water",
        "volume_ml": 200,
        "pack_qty": 1,
        "price": Decimal("1.0163"),
        "raw_desc": "FEVER-TREE MEDITERRANEAN TONIC WATER 200"
    },
    {
        "supplier_code": "NAVAS_FEVER5",
        "sku": "SOFT-FEVER_TREE_PINK_GRAPEFRUIT-20CL-BT",
        "canonical_name": "Fever-Tree Pink Grapefruit 20 cl bottiglia",
        "brand": "Fever-Tree",
        "variant": "Pink Grapefruit",
        "volume_ml": 200,
        "pack_qty": 1,
        "price": Decimal("1.0163"),
        "raw_desc": "FEVER-TREE PINK GRAPEFRUIT 20 CL"
    }
]

async def run_batch(apply: bool):
    supplier_id = 11  # Navas Srl
    today = date.today()
    
    print("=" * 100)
    print(f"⚡ NAVAS PREMIUM MIXERS BATCH 1 - {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 100)
    
    async with async_session_factory() as db:
        async with db.begin():
            # Conteggi pre
            prod_count_before = (await db.execute(select(func.count(Product.id)))).scalar()
            alias_count_before = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            price_count_before = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id, ListinoMaster.data_scadenza.is_(None)))).scalar()
            alias_no_price_before = (await db.execute(
                select(func.count(SupplierProductAlias.id))
                .outerjoin(ListinoMaster, ListinoMaster.supplier_product_alias_id == SupplierProductAlias.id)
                .where(SupplierProductAlias.supplier_id == supplier_id, SupplierProductAlias.status == "approved", ListinoMaster.id.is_(None))
            )).scalar()
            
            print("\n📊 CONTEGGI DB PRE-OPERAZIONE:")
            print(f"  Prodotti Canonici Totali: {prod_count_before}")
            print(f"  Alias Navas Totali:        {alias_count_before}")
            print(f"  Prezzi Navas Attivi:       {price_count_before}")
            print(f"  Alias Approved Senza Prezzo: {alias_no_price_before}")
            print("-" * 100)
            
            products_created = 0
            aliases_created = 0
            prices_created = 0
            
            for conf in PREMIUM_MIXERS_BATCH_1_CONFIG:
                print(f"Descrizione Fornitore: '{conf['raw_desc']}'")
                
                # A. Crea/Verifica Prodotto Canonico
                p_stmt = select(Product).where(Product.sku_interno == conf["sku"])
                prod = (await db.execute(p_stmt)).scalars().first()
                
                if not prod:
                    if apply:
                        prod = Product(
                            sku_interno=conf["sku"],
                            canonical_name=conf["canonical_name"],
                            normalized_name=conf["canonical_name"].lower(),
                            brand=conf["brand"],
                            category="soft_drink",
                            variant=conf["variant"],
                            volume_ml=conf["volume_ml"],
                            unit_count=conf["pack_qty"],
                            container_type="glass_bottle",
                            comparison_unit="liter",
                            is_active=True
                        )
                        db.add(prod)
                        await db.flush()
                        print(f"  ➕ [PRODOTTO] Creato: {conf['sku']} -> {conf['canonical_name']}")
                    else:
                        print(f"  🔍 [PRODOTTO] Da Creare: {conf['sku']} -> {conf['canonical_name']}")
                    products_created += 1
                else:
                    print(f"  ✓ [PRODOTTO] Già Esistente: {conf['sku']}")
                
                # B. Crea/Verifica SupplierProductAlias
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
                            normalized_description=conf["raw_desc"].lower(),
                            pack_qty=conf["pack_qty"],
                            volume_ml=conf["volume_ml"],
                            container_type="glass_bottle",
                            status="approved",
                            confidence_score=100.0,
                            source="manual_override_premium_mixers_batch1"
                        )
                        db.add(alias)
                        await db.flush()
                        print(f"  ➕ [ALIAS] Creato: {conf['supplier_code']} (pack: {conf['pack_qty']}, vol: {conf['volume_ml']}ml)")
                    else:
                        print(f"  🔍 [ALIAS] Da Creare: {conf['supplier_code']} (pack: {conf['pack_qty']}, vol: {conf['volume_ml']}ml)")
                    aliases_created += 1
                else:
                    print(f"  ✓ [ALIAS] Già Esistente: {conf['supplier_code']}")
                    if apply and alias.product_id != prod.id:
                        alias.product_id = prod.id
                        alias.status = "approved"
                        alias.pack_qty = conf["pack_qty"]
                        alias.volume_ml = conf["volume_ml"]
                        db.add(alias)
                        print(f"  ⚡ [ALIAS] Ricollegato ed aggiornato")
                
                # C. Salva Prezzo in ListinoMaster
                litri_totali = (Decimal(str(conf["pack_qty"])) * Decimal(str(conf["volume_ml"]))) / Decimal("1000")
                norm_price = conf["price"] / litri_totali
                
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
                    print(f"  ➕ [PREZZO] Esito: {outcome} | Prezzo Pack: € {conf['price']:.4f} | Normalizzato: € {norm_price:.4f} / L")
                    if outcome in ("created", "updated"):
                        prices_created += 1
                else:
                    print(f"  🔍 [PREZZO] Da Creare: Prezzo Pack = € {conf['price']:.4f} | Normalizzato = € {norm_price:.4f} / L")
                    prices_created += 1
                    
                # D. Risolve MatchCandidate
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
                        print(f"  ⚡ [CANDIDATO] Risolto MatchCandidate per '{conf['raw_desc']}'")
                    else:
                        print(f"  🔍 [CANDIDATO] Verrà risolto MatchCandidate per '{conf['raw_desc']}'")
                print("-" * 50)
                
            if not apply:
                print("\n⚠️ MODALITÀ DRY RUN: Nessun dato salvato (ROLLBACK).")
            else:
                print("\n✅ MODALITÀ APPLY: Dati salvati con successo (COMMIT).")
                
            # Calcola conteggi post
            if not apply:
                prod_count_after = prod_count_before + products_created
                alias_count_after = alias_count_before + aliases_created
                price_count_after = price_count_before + prices_created
                alias_no_price_after = alias_no_price_before
            else:
                await db.flush()
                prod_count_after = (await db.execute(select(func.count(Product.id)))).scalar()
                alias_count_after = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
                price_count_after = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id, ListinoMaster.data_scadenza.is_(None)))).scalar()
                alias_no_price_after = (await db.execute(
                    select(func.count(SupplierProductAlias.id))
                    .outerjoin(ListinoMaster, ListinoMaster.supplier_product_alias_id == SupplierProductAlias.id)
                    .where(SupplierProductAlias.supplier_id == supplier_id, SupplierProductAlias.status == "approved", ListinoMaster.id.is_(None))
                )).scalar()
                
            print("\n📊 CONTEGGI DB POST-OPERAZIONE:")
            print(f"  Prodotti Canonici Totali: {prod_count_after} (Variazione: +{prod_count_after - prod_count_before})")
            print(f"  Alias Navas Totali:        {alias_count_after} (Variazione: +{alias_count_after - alias_count_before})")
            print(f"  Prezzi Navas Attivi:       {price_count_after} (Variazione: +{price_count_after - price_count_before})")
            print(f"  Alias Approved Senza Prezzo: {alias_no_price_after}")
            print("=" * 100)
            
            if not apply:
                raise RuntimeError("Dry run rollback trigger")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approve Navas premium mixers batch 1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Simulate import process")
    group.add_argument("--apply", action="store_true", help="Execute database changes")
    
    args = parser.parse_args()
    try:
        asyncio.run(run_batch(apply=args.apply))
    except RuntimeError as e:
        if str(e) != "Dry run rollback trigger":
            raise
