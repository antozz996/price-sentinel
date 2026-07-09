import asyncio
import argparse
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price

suspect_configurations = [
    {
        "desc": "ACQUA VERA 2LT",
        "sku": "ACQ-VERA-200CL",
        "supplier_code": "NAVAS_ACQU013",
        "price": Decimal("1.4760"),
        "volume_ml": 2000,
        "comparison_unit": "liter",
        "original_pack": 1,
        "proposed_pack": 6,
        "uom": "piece",
        "motivation": "Il prezzo di € 1.4760 corrisponde allo standard fardello x6 di acqua minerale da 2L (circa € 0.246 per bottiglia). Un prezzo unitario di € 1.4760 al litro sarebbe anomalo."
    },
    {
        "desc": "ACQUA FERRARELLE 0.75 VR VETRO",
        "sku": "ACQ-FERRARELLE-75CL",
        "supplier_code": "NAVAS_ACQUA002",
        "price": Decimal("5.3275"),
        "volume_ml": 750,
        "comparison_unit": "liter",
        "original_pack": 1,
        "proposed_pack": 12,
        "uom": "piece",
        "motivation": "Le bottiglie in vetro a rendere (VAR/VR) Ferrarelle da 75cl vengono distribuite in casse da 12 bottiglie. € 5.3275 per cassa (circa € 0.44 a bottiglia) è plausibile; € 7.10 al litro per acqua sarebbe fuori mercato."
    },
    {
        "desc": "CEDRATA SAN BENEDETTO 1,5 LT",
        "sku": "SOFT-CEDRATA_SAN_BENEDETTO-150CL",
        "supplier_code": "NAVAS_CEDR8621",
        "price": Decimal("3.2800"),
        "volume_ml": 1500,
        "comparison_unit": "liter",
        "original_pack": 1,
        "proposed_pack": 6,
        "uom": "piece",
        "motivation": "Le bibite San Benedetto in PET da 1.5L sono tradizionalmente confezionate in fardelli da 6. Con pack=6, il prezzo per bottiglia è € 0.5467 (prezzo al litro € 0.3644), estremamente plausibile per l'ingrosso. Con pack=4, il prezzo a bottiglia sarebbe € 0.82 (prezzo al litro € 0.5466) che risulta meno comune per canali distributivi B2B."
    }
]

def calculate_norm_price_liters(price, pack_qty, volume_ml):
    total_liters = (Decimal(str(pack_qty)) * Decimal(str(volume_ml))) / Decimal("1000")
    return Decimal(str(price)) / total_liters

async def run_operation(mode: str):
    supplier_id = 11
    today = date.today()
    
    async with async_session_factory() as db:
        # Analisi in Dry-Run
        if mode == "dry-run":
            print("\n" + "="*90)
            print("🛡️ DRY-RUN: ANALISI OVERRIDE MANUALE PACK SUSPECTS")
            print("="*90)
            
            for config in suspect_configurations:
                desc = config["desc"]
                sku = config["sku"]
                price = config["price"]
                vol = config["volume_ml"]
                original_pack = config["original_pack"]
                proposed_pack = config["proposed_pack"]
                
                # Calcola prezzi normalizzati
                orig_norm = calculate_norm_price_liters(price, original_pack, vol)
                proposed_norm = calculate_norm_price_liters(price, proposed_pack, vol)
                
                print(f"Descrizione originale: '{desc}'")
                print(f"  * Codice Fornitore:   {config['supplier_code']}")
                print(f"  * SKU Target:         {sku}")
                print(f"  * Prezzo Listino:     € {price:.4f}")
                print(f"  * Pack Originale:     {original_pack}  -> Normalizzato: € {orig_norm:.4f}/L (Sospetto)")
                print(f"  * Pack Proposto:      {proposed_pack}  -> Normalizzato: € {proposed_norm:.4f}/L (Plausibile)")
                print(f"  * Valutazione:        Plausibile (con override)")
                print(f"  * Motivazione:        {config['motivation']}")
                
                if desc == "CEDRATA SAN BENEDETTO 1,5 LT":
                    norm_pack_4 = calculate_norm_price_liters(price, 4, vol)
                    print(f"    [Analisi Alternativa Cedrata]")
                    print(f"    - Pack = 4 -> Prezzo unitario = € {price/4:.4f} (€ {norm_pack_4:.4f}/L)")
                    print(f"    - Pack = 6 -> Prezzo unitario = € {price/6:.4f} (€ {proposed_norm:.4f}/L) <-- CONSIGLIATO (Standard industriale fardelli)")
                    
                print("-"*50)
            print("="*90 + "\n")
            return
            
        # Modalità APPLY
        elif mode == "apply":
            print("Esecuzione in modalità APPLY: Inserimento override per i 3 pack suspects...")
            aliases_created = 0
            prices_created = 0
            
            async with db.begin():
                for config in suspect_configurations:
                    # Controlla se alias già esiste per evitare duplicazioni
                    exists_stmt = select(SupplierProductAlias).where(
                        SupplierProductAlias.supplier_id == supplier_id,
                        SupplierProductAlias.raw_description == config["desc"],
                        SupplierProductAlias.status == "approved"
                    )
                    alias_exists = (await db.execute(exists_stmt)).scalars().first()
                    if alias_exists:
                        print(f"Alias per '{config['desc']}' già esistente. Salto.")
                        continue
                        
                    # Recupera ID del prodotto target
                    p_stmt = select(Product.id).where(Product.sku_interno == config["sku"])
                    prod_id = (await db.execute(p_stmt)).scalar()
                    if not prod_id:
                        print(f"Errore: Prodotto con SKU {config['sku']} non trovato!")
                        continue
                        
                    # 1. Crea SupplierProductAlias
                    alias = SupplierProductAlias(
                        supplier_id=supplier_id,
                        product_id=prod_id,
                        supplier_code=config["supplier_code"],
                        raw_description=config["desc"],
                        normalized_description=config["desc"].lower(),
                        pack_qty=config["proposed_pack"],
                        volume_ml=config["volume_ml"],
                        status="approved",
                        confidence_score=95.00,
                        source="manual_override_pack"
                    )
                    db.add(alias)
                    aliases_created += 1
                    
                    # 2. Salva in ListinoMaster
                    await db.flush()
                    outcome = await save_append_only_price(
                        db=db,
                        fornitore_id=supplier_id,
                        sku_interno=config["sku"],
                        descrizione=config["desc"],
                        prezzo_pattuito=config["price"],
                        unita_misura=config["uom"],
                        data_inizio=today,
                        supplier_product_alias_id=alias.id
                    )
                    if outcome in ("created", "updated"):
                        prices_created += 1
                        
            print(f"Applicazione completata! Alias creati: {aliases_created}, Prezzi contrattualizzati: {prices_created}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Approve suspect pack configurations with override")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Analizza e mostra l'impatto degli override")
    group.add_argument("--apply", action="store_true", help="Salva gli override approvati a database")
    args = parser.parse_args()
    
    mode_str = "dry-run"
    if args.apply:
        mode_str = "apply"
        
    asyncio.run(run_operation(mode_str))
