import asyncio
import argparse
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price

AMARI_BATCH_1_CONFIG = [
    {
        "supplier_code": "NAVAS_AMA432",
        "sku": "BEV-AMARA_AMARO-70CL",
        "canonical_name": "Amaro Amara 70 cl",
        "brand": "Amara",
        "volume_ml": 700,
        "pack_qty": 1,
        "price": Decimal("19.2600"),
        "raw_desc": "AMARO AMARA 70 CL"
    },
    {
        "supplier_code": "NAVAS_AMARA987",
        "sku": "BEV-AMARA_ARANCIA-50CL",
        "canonical_name": "Amaro Amara Arancia di Sicilia 50 cl",
        "brand": "Amara",
        "volume_ml": 500,
        "pack_qty": 1,
        "price": Decimal("16.8050"),
        "raw_desc": "AMARO AMARA ARANCIA DI SICILIA 30° 50 CL"
    },
    {
        "supplier_code": "NAVAS_AMARO04",
        "sku": "BEV-AMARO_DEL_CAPO-70CL",
        "canonical_name": "Amaro del Capo 70 cl",
        "brand": "Del Capo",
        "volume_ml": 700,
        "pack_qty": 1,
        "price": Decimal("8.1963"),
        "raw_desc": "AMARO DEL CAPO CL 70"
    },
    {
        "supplier_code": "NAVAS_AMARO12",
        "sku": "BEV-JEFFERSON_AMARO-70CL",
        "canonical_name": "Amaro Jefferson 70 cl",
        "brand": "Jefferson",
        "volume_ml": 700,
        "pack_qty": 1,
        "price": Decimal("20.4917"),
        "raw_desc": "AMARO JEFFERSON CL 70"
    },
    {
        "supplier_code": "NAVAS_APER004",
        "sku": "BEV-APEROL-100CL",
        "canonical_name": "Aperol 100 cl",
        "brand": "Aperol",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("10.6550"),
        "raw_desc": "APEROL  1LITRO  BT"
    },
    {
        "supplier_code": "NAVAS_BAILEYS1",
        "sku": "BEV-BAILEYS-100CL",
        "canonical_name": "Baileys Cream 100 cl",
        "brand": "Baileys",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("12.3000"),
        "raw_desc": "BAILEYS CREAM 100 CL"
    },
    {
        "supplier_code": "NAVAS_BITTER5",
        "sku": "BEV-CAMPARI_BITTER-100CL",
        "canonical_name": "Campari Bitter 100 cl",
        "brand": "Campari",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("13.1967"),
        "raw_desc": "BITTER CAMPARI CL.100"
    },
    {
        "supplier_code": "NAVAS_DIS02",
        "sku": "BEV-DISARONNO-100CL",
        "canonical_name": "Disaronno 100 cl",
        "brand": "Disaronno",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("14.7533"),
        "raw_desc": "DISARONNO 1 LT"
    },
    {
        "supplier_code": "NAVAS_JAGM02",
        "sku": "BEV-JAGERMEISTER-100CL",
        "canonical_name": "Jagermeister 100 cl",
        "brand": "Jagermeister",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("12.2950"),
        "raw_desc": "JAGERMEISTER 100 CL"
    },
    {
        "supplier_code": "NAVAS_LIQ12",
        "sku": "BEV-MALIBU-100CL",
        "canonical_name": "Malibu 100 cl",
        "brand": "Malibu",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("11.4750"),
        "raw_desc": "MALIBU 100 CL"
    },
    {
        "supplier_code": "NAVAS_PASSO01",
        "sku": "BEV-PASSOA-100CL",
        "canonical_name": "Passoa 100 cl",
        "brand": "Passoa",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("12.2950"),
        "raw_desc": "PASSOA LT 1"
    },
    {
        "supplier_code": "NAVAS_SAM02",
        "sku": "BEV-SAMBUCA_MOLINARI-70CL",
        "canonical_name": "Sambuca Molinari 70 cl",
        "brand": "Molinari",
        "volume_ml": 700,
        "pack_qty": 1,
        "price": Decimal("9.8367"),
        "raw_desc": "SAMBUCA MOLINARI 70 CL"
    },
    {
        "supplier_code": "NAVAS_SAMB022",
        "sku": "BEV-SAMBUCA_RAMAZZOTTI-100CL",
        "canonical_name": "Sambuca Ramazzotti 100 cl",
        "brand": "Ramazzotti",
        "volume_ml": 1000,
        "pack_qty": 1,
        "price": Decimal("10.6550"),
        "raw_desc": "SAMBUCA RAMAZZOTTI 100 CL"
    }
]

async def run_batch(apply: bool):
    supplier_id = 11  # Navas Srl
    today = date.today()
    
    print("=" * 100)
    print(f"🥃 NAVAS AMARI & LIQUORI BATCH 1 - {'APPLY' if apply else 'DRY RUN'} (CLEAN SINGLE BOTTLES)")
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
            
            for conf in AMARI_BATCH_1_CONFIG:
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
                            category="beverage",
                            volume_ml=conf["volume_ml"],
                            unit_count=1,
                            container_type="glass_bottle",
                            comparison_unit="bottle",
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
                            status="approved",
                            confidence_score=100.0,
                            source="manual_override_amari_batch1"
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
                    print(f"  ➕ [PREZZO] Esito: {outcome} | Prezzo Pack: € {conf['price']:.4f} | Normalizzato: € {conf['price']:.4f} / bottle")
                    if outcome in ("created", "updated"):
                        prices_created += 1
                else:
                    print(f"  🔍 [PREZZO] Da Creare: Prezzo Pack = € {conf['price']:.4f} | Normalizzato = € {conf['price']:.4f} / bottle")
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
    parser = argparse.ArgumentParser(description="Approve Navas amari batch 1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Simulate import process")
    group.add_argument("--apply", action="store_true", help="Execute database changes")
    
    args = parser.parse_args()
    try:
        asyncio.run(run_batch(apply=args.apply))
    except RuntimeError as e:
        if str(e) != "Dry run rollback trigger":
            raise
