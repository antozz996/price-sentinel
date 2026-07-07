import asyncio
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func, and_
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, MatchCandidate
from app.models.listino import ListinoMaster
from app.services.supplier_list_import import save_append_only_price
from app.services.order_resolver import resolve_order_item

batch2_mappings = [
    {"desc": "LIMONCELLO 200 CL", "sku": "BEV-LIMONCELLO-200CL"},
    {"desc": "RUM ZACAPA 23 DA 70 CL", "sku": "BEV-ZACAPA_23_RUM-70CL"},
    {"desc": "VINO CHARDONNAY JERMANN 75 CL", "sku": "BEV-JERMANN_CHARDONNAY-75CL"},
    {"desc": "VODKA GREY GOOSE 70 CL", "sku": "BEV-GREY_GOOSE_VODKA-70CL"},
    {"desc": "VODKA ABSOLUT 1 LT", "sku": "BEV-ABSOLUT_VODKA-100CL"},
    {"desc": "VODKA ABSOLUT 70 CL", "sku": "BEV-ABSOLUT_VODKA-70CL"},
    {"desc": "VODKA BELVEDERE 70 CL", "sku": "BEV-BELVEDERE_VODKA-70CL"},
]

async def run_approval():
    supplier_id = 11
    today = date.today()
    
    async with async_session_factory() as db:
        # Conteggi prima
        async with db.begin():
            mc_pending_before = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id, MatchCandidate.status == "pending"))).scalar()
            mc_resolved_before = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id, MatchCandidate.status == "resolved"))).scalar()
            alias_before = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            lm_before = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id))).scalar()
            prod_before = (await db.execute(select(func.count(Product.id)))).scalar()

        # Raccogli e visualizza i 7 candidati prima di approvarli
        approval_rows = []
        async with db.begin():
            for mapping in batch2_mappings:
                desc = mapping["desc"]
                target_sku = mapping["sku"]
                
                # Trova il candidato
                stmt = select(MatchCandidate).where(
                    MatchCandidate.supplier_id == supplier_id,
                    MatchCandidate.raw_description == desc,
                    MatchCandidate.status == "pending"
                )
                mc = (await db.execute(stmt)).scalars().first()
                if not mc:
                    print(f"Attenzione: Candidato non trovato o già risolto per '{desc}'")
                    continue
                
                # Trova il prodotto target
                p_stmt = select(Product).where(Product.sku_interno == target_sku)
                prod = (await db.execute(p_stmt)).scalars().first()
                if not prod:
                    print(f"Errore: Prodotto target {target_sku} non trovato in anagrafica!")
                    continue
                
                reason = mc.reason_json or {}
                price = reason.get("price", 0.0)
                pack_qty = reason.get("pack_qty", 1)
                volume_ml = reason.get("volume_ml") or prod.volume_ml or 700
                uom = reason.get("uom", "piece")
                warning = reason.get("warning")
                
                # Per bottiglie/pezzi, il prezzo normalizzato coincide con il prezzo unitario della bottiglia (pack_qty=1)
                norm_price = Decimal(str(price)) / Decimal(str(pack_qty))
                
                # Valutazione del prezzo
                plausibility = "Plausibile"
                if pack_qty == 1 and price < 2.0:
                    plausibility = "Sospetto (Prezzo troppo basso per superalcolico/vino)"
                
                approval_rows.append({
                    "mc_id": mc.id,
                    "raw_desc": desc,
                    "supplier_code": reason.get("supplier_code"),
                    "target_sku": target_sku,
                    "price": price,
                    "pack_qty": pack_qty,
                    "volume_ml": volume_ml,
                    "comparison_unit": prod.comparison_unit,
                    "norm_price": norm_price,
                    "warning": warning,
                    "plausibility": plausibility,
                    "match_candidate_obj": mc,
                    "product_obj": prod
                })

        print("\n" + "="*80)
        print("📑 CANDIDATI DI BATCH 2 PRONTI PER L'APPROVAZIONE MANUALE (WINE & SPIRITS)")
        print("="*80)
        for row in approval_rows:
            print(f"Candidate ID: {row['mc_id']}")
            print(f"  * Descrizione:     '{row['raw_desc']}'")
            print(f"  * Codice Forn:     '{row['supplier_code']}'")
            print(f"  * SKU Target:       {row['target_sku']}")
            print(f"  * Prezzo Org (UOM): € {row['price']:.4f} ({row['comparison_unit']})")
            print(f"  * Pack Qty / Vol:   {row['pack_qty']} pz / {row['volume_ml']} ml")
            print(f"  * Prezzo Normaliz:  € {row['norm_price']:.4f} a bottiglia")
            print(f"  * Valutazione:      {row['plausibility']}")
            print(f"  * Warning:          {row['warning']}")
            print("-"*50)
        print("="*80 + "\n")

        # Esegui l'approvazione scrivendo a database in una singola transazione
        aliases_created = 0
        prices_created = 0
        
        async with db.begin():
            for row in approval_rows:
                mc = row["match_candidate_obj"]
                prod = row["product_obj"]
                reason = mc.reason_json or {}
                
                # 1. Crea SupplierProductAlias
                alias = SupplierProductAlias(
                    supplier_id=supplier_id,
                    product_id=prod.id,
                    supplier_code=row["supplier_code"],
                    raw_description=row["raw_desc"],
                    normalized_description=mc.normalized_description,
                    pack_qty=row["pack_qty"],
                    volume_ml=row["volume_ml"],
                    status="approved",
                    confidence_score=mc.score,
                    source="manual_approval"
                )
                db.add(alias)
                aliases_created += 1
                
                # 2. Crea/Aggiorna prezzo in ListinoMaster (usa il prezzo della confezione letto da Excel)
                outcome = await save_append_only_price(
                    db=db,
                    fornitore_id=supplier_id,
                    sku_interno=row["target_sku"],
                    descrizione=row["raw_desc"],
                    prezzo_pattuito=Decimal(str(row["price"])),
                    unita_misura=reason.get("uom", "piece"),
                    data_inizio=today
                )
                if outcome in ("created", "updated"):
                    prices_created += 1
                
                # 3. Aggiorna lo stato del MatchCandidate a 'resolved'
                mc.status = "resolved"
                mc.resolved_at = datetime.utcnow()
                db.add(mc)
                
        # Conteggi dopo
        async with db.begin():
            mc_pending_after = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id, MatchCandidate.status == "pending"))).scalar()
            mc_resolved_after = (await db.execute(select(func.count(MatchCandidate.id)).where(MatchCandidate.supplier_id == supplier_id, MatchCandidate.status == "resolved"))).scalar()
            alias_after = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == supplier_id))).scalar()
            lm_after = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == supplier_id))).scalar()
            prod_after = (await db.execute(select(func.count(Product.id)))).scalar()

        print("="*80)
        print("📈 VERIFICA CONTEGGI POST APPROVAZIONE BATCH 2")
        print("="*80)
        print(f"Product:                  Prima={prod_before} | Dopo={prod_after} | Diff={prod_after - prod_before} (Invariato)")
        print(f"Alias (Fornitore 11):     Prima={alias_before} | Dopo={alias_after} | Diff={alias_after - alias_before} (Attesi +7)")
        print(f"Listino (Fornitore 11):   Prima={lm_before} | Dopo={lm_after} | Diff={lm_after - lm_before} (Attesi +7)")
        print(f"Candidati PENDING:        Prima={mc_pending_before} | Dopo={mc_pending_after} | Diff={mc_pending_after - mc_pending_before} (Attesi -7)")
        print(f"Candidati RESOLVED:       Prima={mc_resolved_before} | Dopo={mc_resolved_after} | Diff={mc_resolved_after - mc_resolved_before} (Attesi +7)")
        print("="*80 + "\n")

        # Esegui Test Resolver Ordine su almeno i 5 prodotti richiesti
        print("="*80)
        print("🔍 VERIFICA DI SIMULAZIONE ORDER RESOLVER (OTTIMIZZATORE)")
        print("="*80)
        test_skus = [
            "BEV-ABSOLUT_VODKA-100CL",
            "BEV-ABSOLUT_VODKA-70CL",
            "BEV-BELVEDERE_VODKA-70CL",
            "BEV-ZACAPA_23_RUM-70CL",
            "BEV-LIMONCELLO-200CL"
        ]
        
        # Simula un ordine con 10 unità/bottiglie richieste per ciascuno
        for sku in test_skus:
            # Trova il prodotto
            p_stmt = select(Product).where(Product.sku_interno == sku)
            p_obj = (await db.execute(p_stmt)).scalars().first()
                
            if not p_obj:
                print(f"SKU {sku} non trovato nel DB per il test resolver.")
                continue
                
            # Risolvi offerta ottimale
            res_opt = await resolve_order_item(
                db=db,
                query=sku,
                requested_qty=Decimal("10"),
                location_id=1
            )
            
            opt = res_opt.get("best_offer")
            print(f"SKU: {sku} ({p_obj.canonical_name}) | Unità Richieste: 10")
            if opt:
                print(f"  * Migliore Offerta: Fornitore='{opt.get('supplier_name')}' | Prezzo Unitario normalizzato: € {opt.get('unit_price_normalized')} a bottiglia")
                print(f"  * Dettaglio: Prezzo Pack = € {opt.get('price_per_pack')} | Confezioni necessarie = {opt.get('packs_needed')} | Unità effettive fornite = {opt.get('actual_units_supplied')}")
            else:
                print("  * Nessuna offerta trovata.")
            print("-"*50)
        print("="*80 + "\n")

if __name__ == "__main__":
    asyncio.run(run_approval())
