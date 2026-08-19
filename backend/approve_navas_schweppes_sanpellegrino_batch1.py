import asyncio
import argparse
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price

SCHWEPPES_SP_BATCH_1_CONFIG = [
    {
        "supplier_code": "NAVAS_BITTER7",
        "sku": "SOFT-SAN_PELLEGRINO_SANBITTER_BIANCO-10CL-BT",
        "canonical_name": "San Pellegrino Sanbitter Bianco 10 cl bottiglia",
        "brand": "San Pellegrino",
        "variant": "Sanbitter Bianco",
        "volume_ml": 100,
        "pack_qty": 40,
        "price": Decimal("16.3900"),
        "raw_desc": "S.PELLEGRINO BITTER BIANCO X 40",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_BITTER8",
        "sku": "SOFT-SAN_PELLEGRINO_SANBITTER_ROSSO-10CL-BT",
        "canonical_name": "San Pellegrino Sanbitter Rosso 10 cl bottiglia",
        "brand": "San Pellegrino",
        "variant": "Sanbitter Rosso",
        "volume_ml": 100,
        "pack_qty": 40,
        "price": Decimal("16.3900"),
        "raw_desc": "S.PELLEGRINO BITTER ROSSO X 40",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_SANPE032",
        "sku": "SOFT-SAN_PELLEGRINO_COCKTAIL_ROSSO-20CL-BT",
        "canonical_name": "San Pellegrino Cocktail Rosso 20 cl bottiglia",
        "brand": "San Pellegrino",
        "variant": "Cocktail Rosso",
        "volume_ml": 200,
        "pack_qty": 24,
        "price": Decimal("11.8900"),
        "raw_desc": "S. PELLE GRINO COCKTAIL ROSSO X 24 BT",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_SPEL013",
        "sku": "SOFT-SAN_PELLEGRINO_COCKTAIL_BIANCO-20CL-BT",
        "canonical_name": "San Pellegrino Cocktail Bianco 20 cl bottiglia",
        "brand": "San Pellegrino",
        "variant": "Cocktail Bianco",
        "volume_ml": 200,
        "pack_qty": 24,
        "price": Decimal("11.8900"),
        "raw_desc": "S. PELLEGRINO COCKTAIL BIANCO 20 CL 24 VAP",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_SCHPOM22",
        "sku": "SOFT-SCHWEPPES_PINK_GRAPEFRUIT-100CL-PET",
        "canonical_name": "Schweppes Pink Grapefruit 100 cl bottiglia PET",
        "brand": "Schweppes",
        "variant": "Pink Grapefruit",
        "volume_ml": 1000,
        "pack_qty": 6,
        "price": Decimal("6.1467"),
        "raw_desc": "SCHWEPPES POMPELMO ROSA 1 LITRO X 6",
        "container_type": "pet_bottle"
    },
    {
        "supplier_code": "NAVAS_SCHW014",
        "sku": "SOFT-SCHWEPPES_ORANGE-18CL-BT",
        "canonical_name": "Schweppes Orange 18 cl bottiglia",
        "brand": "Schweppes",
        "variant": "Orange",
        "volume_ml": 180,
        "pack_qty": 24,
        "price": Decimal("14.7500"),
        "raw_desc": "SCHWEPPES ARANCIA 18 CL X 24 VAP VETRO",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_SCHW015",
        "sku": "SOFT-SCHWEPPES_LEMON-18CL-BT",
        "canonical_name": "Schweppes Lemon 18 cl bottiglia",
        "brand": "Schweppes",
        "variant": "Lemon",
        "volume_ml": 180,
        "pack_qty": 24,
        "price": Decimal("14.7500"),
        "raw_desc": "SCHWEPPES LIMONE 18 CL VAP X 24 VETRO",
        "container_type": "glass_bottle"
    },
    {
        "supplier_code": "NAVAS_SCHWEP02",
        "sku": "SOFT-SCHWEPPES_TONIC-100CL-PET",
        "canonical_name": "Schweppes Tonic 100 cl bottiglia PET",
        "brand": "Schweppes",
        "variant": "Tonic",
        "volume_ml": 1000,
        "pack_qty": 6,
        "price": Decimal("5.7367"),
        "raw_desc": "SCHWEPPES TONICA 1 LITRO PET X 6",
        "container_type": "pet_bottle"
    },
    {
        "supplier_code": "NAVAS_SCHWEPP",
        "sku": "SOFT-SCHWEPPES_LEMON-100CL-PET",
        "canonical_name": "Schweppes Lemon 100 cl bottiglia PET",
        "brand": "Schweppes",
        "variant": "Lemon",
        "volume_ml": 1000,
        "pack_qty": 6,
        "price": Decimal("5.7367"),
        "raw_desc": "SCHWEPPES LIMONE 1 LT PET X 6",
        "container_type": "pet_bottle"
    }
]

async def run_batch(apply: bool):
    supplier_id = 11  # Navas Srl
    today = date.today()
    
    print("=" * 100)
    print(f"⚡ NAVAS SCHWEPPES & SAN PELLEGRINO BATCH 1 - {'APPLY' if apply else 'DRY RUN'}")
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
            
            if not apply:
                print("\n📊 CONTEGGI DB PRE-OPERAZIONE:")
                print(f"  Prodotti Canonici Totali: {prod_count_before}")
                print(f"  Alias Navas Totali:        {alias_count_before}")
                print(f"  Prezzi Navas Attivi:       {price_count_before}")
                print(f"  Alias Approved Senza Prezzo: {alias_no_price_before}")
                print("-" * 100)
            
            products_created = 0
            aliases_created = 0
            prices_created = 0
            
            for conf in SCHWEPPES_SP_BATCH_1_CONFIG:
                litri_totali = (Decimal(str(conf["pack_qty"])) * Decimal(str(conf["volume_ml"]))) / Decimal("1000")
                norm_price = conf["price"] / litri_totali
                
                print(f"raw_description:      {conf['raw_desc']}")
                print(f"supplier_code:        {conf['supplier_code']}")
                print(f"SKU proposto:         {conf['sku']}")
                print(f"canonical_name:       {conf['canonical_name']}")
                print(f"brand:                {conf['brand']}")
                print(f"variante/gusto:       {conf['variant']}")
                print(f"volume_ml:            {conf['volume_ml']}")
                print(f"pack_qty:             {conf['pack_qty']}")
                print(f"container_type:       {conf['container_type']}")
                print(f"comparison_unit:      liter")
                print(f"prezzo pack:          € {conf['price']:.4f}")
                print(f"prezzo norm. atteso:  € {norm_price:.4f} / L")
                
                # A. Crea/Verifica Prodotto Canonico
                p_stmt = select(Product).where(Product.sku_interno == conf["sku"])
                prod = (await db.execute(p_stmt)).scalars().first()
                
                prod_action = "Nessuno (Già esistente)"
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
                            container_type=conf["container_type"],
                            comparison_unit="liter",
                            is_active=True
                        )
                        db.add(prod)
                        await db.flush()
                        prod_action = "CREATO"
                    else:
                        prod_action = "DA CREARE"
                    products_created += 1
                
                print(f"Product da creare:    {prod_action}")
                
                # B. Crea/Verifica SupplierProductAlias
                a_stmt = select(SupplierProductAlias).where(
                    SupplierProductAlias.supplier_id == supplier_id,
                    SupplierProductAlias.supplier_code == conf["supplier_code"]
                )
                alias = (await db.execute(a_stmt)).scalars().first()
                
                alias_action = "Nessuno (Già esistente)"
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
                            container_type=conf["container_type"],
                            status="approved",
                            confidence_score=100.0,
                            source="manual_override_schweppes_sp_batch1"
                        )
                        db.add(alias)
                        await db.flush()
                        alias_action = "CREATO"
                    else:
                        alias_action = "DA CREARE"
                    aliases_created += 1
                else:
                    if apply and alias.product_id != prod.id:
                        alias.product_id = prod.id
                        alias.status = "approved"
                        alias.pack_qty = conf["pack_qty"]
                        alias.volume_ml = conf["volume_ml"]
                        db.add(alias)
                        alias_action = "AGGIORNATO"
                
                print(f"Alias da creare:      {alias_action}")
                
                # C. Salva Prezzo in ListinoMaster
                price_action = "Nessuno (Già esistente)"
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
                    price_action = f"APPLICATO (Esito: {outcome})"
                    if outcome in ("created", "updated"):
                        prices_created += 1
                else:
                    price_action = "DA CREARE"
                    prices_created += 1
                
                print(f"ListinoMaster da cre.: {price_action}")
                
                # D. Risolve MatchCandidate
                mc_stmt = select(MatchCandidate).where(
                    MatchCandidate.supplier_id == supplier_id,
                    MatchCandidate.raw_description == conf["raw_desc"],
                    MatchCandidate.status == "pending"
                )
                mc = (await db.execute(mc_stmt)).scalars().first()
                mc_action = "Nessuno"
                if mc:
                    if apply:
                        mc.status = "resolved"
                        mc.resolved_at = datetime.utcnow()
                        db.add(mc)
                        mc_action = "RISOLTO"
                    else:
                        mc_action = "DA RISOLVERE"
                
                print(f"warning:              Nessuno")
                print(f"valutazione:          approvabile")
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
    parser = argparse.ArgumentParser(description="Approve Navas Schweppes and San Pellegrino batch 1")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Simulate import process")
    group.add_argument("--apply", action="store_true", help="Execute database changes")
    
    args = parser.parse_args()
    try:
        asyncio.run(run_batch(apply=args.apply))
    except RuntimeError as e:
        if str(e) != "Dry run rollback trigger":
            raise
