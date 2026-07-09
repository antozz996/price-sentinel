import asyncio
import json
import os
from decimal import Decimal
from sqlalchemy import select, func, or_, case
from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias
from app.models.listino import ListinoMaster
from app.services.matching import normalize_price_for_comparison
from app.services.order_resolver import resolve_order_item

async def run_report():
    async with async_session_factory() as db:
        async with db.begin():
            # 1. Conteggi Generali
            tot_products = (await db.execute(select(func.count(Product.id)))).scalar()
            tot_aliases = (await db.execute(select(func.count(SupplierProductAlias.id)).where(SupplierProductAlias.supplier_id == 11))).scalar()
            tot_prices = (await db.execute(select(func.count(ListinoMaster.id)).where(ListinoMaster.fornitore_id == 11, ListinoMaster.data_scadenza.is_(None)))).scalar()
            
        # 2. Lista Prodotti Usabili
        usable_list = []
        async with db.begin():
            # Seleziona tutti gli alias approvati di Navas
            alias_stmt = select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == 11, SupplierProductAlias.status == "approved")
            aliases = (await db.execute(alias_stmt)).scalars().all()
            
            for alias in aliases:
                p = alias.product
                # Cerca il prezzo contrattualizzato attivo (specifico per alias o generico)
                l_stmt = select(ListinoMaster).where(
                    ListinoMaster.fornitore_id == 11,
                    ListinoMaster.sku_interno == p.sku_interno,
                    or_(
                        ListinoMaster.supplier_product_alias_id == alias.id,
                        ListinoMaster.supplier_product_alias_id.is_(None)
                    ),
                    ListinoMaster.data_scadenza.is_(None)
                ).order_by(
                    case(
                        (ListinoMaster.supplier_product_alias_id == alias.id, 1),
                        else_=0
                    ).desc(),
                    ListinoMaster.data_inizio_validita.desc(),
                    ListinoMaster.id.desc()
                ).limit(1)
                l = (await db.execute(l_stmt)).scalar_one_or_none()
                
                prezzo_pack = l.prezzo_pattuito if l else Decimal("0")
                prezzo_uom = l.unita_misura if l else "piece"
                
                # Calcola il prezzo normalizzato
                res_norm = normalize_price_for_comparison(
                    price_or_line=prezzo_pack,
                    quantity_or_product=Decimal("1"),
                    invoice_uom=prezzo_uom,
                    product=p,
                    alias=alias
                )
                
                usable_list.append({
                    "sku": p.sku_interno,
                    "name": p.canonical_name,
                    "raw_desc": alias.raw_description,
                    "supplier_code": alias.supplier_code,
                    "price_pack": prezzo_pack,
                    "pack_qty": alias.pack_qty,
                    "volume_ml": alias.volume_ml,
                    "comparison_unit": p.comparison_unit,
                    "normalized_price": res_norm.normalized_unit_price,
                    "category": p.category
                })
                
        # 3. Test resolver ordine misto
        order_queries = [
            ("ACQ-ELECTA-50CL", "Acqua Electa 50cl"),
            ("ACQ-FERRARELLE-50CL", "Acqua Ferrarelle 50cl"),
            ("ACQ-FERRARELLE-75CL", "Acqua Ferrarelle 75cl vetro"),
            ("ACQ-VERA-200CL", "Acqua Vera 2L"),
            ("SOFT-COCA_COLA_ZERO-33CL", "Coca Cola Zero 33cl"),
            ("SOFT-COCA_COLA_ZERO-150CL", "Coca Cola Zero 1.5L"),
            ("SOFT-SCHWEPPES_TONICA-18CL", "Schweppes Tonica 18cl"),
            ("SOFT-CEDRATA_SAN_BENEDETTO-150CL", "Cedrata San Benedetto 1.5L"),
            ("BEV-ABSOLUT_VODKA-100CL", "Absolut 1L"),
            ("BEV-BELVEDERE_VODKA-70CL", "Belvedere 70cl"),
            ("BEV-ZACAPA_23_RUM-70CL", "Zacapa 70cl"),
            ("BEV-LIMONCELLO-200CL", "Limoncello 2L")
        ]
        
        resolver_results = []
        for sku, display_name in order_queries:
            # Esegui risoluzione
            res = await resolve_order_item(
                db=db,
                query=sku,
                requested_qty=Decimal("100") if "ACQ" in sku or "SOFT" in sku else Decimal("10"),
                location_id=1
            )
            opt = res.get("best_offer")
            resolver_results.append({
                "query": display_name,
                "sku": sku,
                "resolved": res.get("decision") == "resolved",
                "supplier": opt.get("supplier_name") if opt else None,
                "price_norm": opt.get("unit_price_normalized") if opt else None,
                "price_pack": opt.get("price_per_pack") if opt else None,
                "packs_needed": opt.get("packs_needed") if opt else None,
                "warning": ", ".join(res.get("warnings", []))
            })

        # 4. Carica il report del gate per capire gli esclusi
        gate_report_path = "data/import_samples/safe_import_gate_report.json"
        excluded_groups = {
            "brand_mismatch": [],
            "no_candidate": [],
            "prodotto_mancante": [],
            "pack_ambiguo": [],
            "possibile_nuovo_prodotto": []
        }
        
        if os.path.exists(gate_report_path):
            with open(gate_report_path, "r") as f:
                data_report = json.load(f)
            
            # Dividi le righe in base alle classificazioni
            # 1. rejected_candidate_brand_mismatch -> brand mismatch
            groups = data_report.get("groups", {})
            for item in groups.get("rejected_candidate_brand_mismatch", []):
                excluded_groups["brand_mismatch"].append(f"{item['raw_description']} (Incompatibile con {item.get('candidate_sku') or 'N/A'})")
                
            # 2. manual_review_no_candidate -> no candidate
            for item in groups.get("manual_review_no_candidate", []):
                desc = item['raw_description']
                score = item.get('score', 0)
                if score > 0:
                    excluded_groups["prodotto_mancante"].append(f"{desc} (Score fuzzy {score} non sufficiente per {item.get('candidate_sku') or 'N/A'})")
                else:
                    excluded_groups["no_candidate"].append(desc)

        # Mostra il report
        print("\n" + "="*80)
        print("📊 NAVAS OPERATIONAL REPORT v1")
        print("="*80)
        print(f"1. Totale Product canonici a catalogo:     {tot_products}")
        print(f"2. Totale alias Navas approvati:            {tot_aliases}")
        print(f"3. Totale prezzi Navas attivi in listino:   {tot_prices}")
        print("="*80)
        
        print("\n4. LISTA COMPLETA PRODOTTI NAVAS UTILIZZABILI:")
        print(f"{'SKU':<35} | {'Brand/Name':<35} | {'Price Pack':<10} | {'Pack':<5} | {'Vol (ml)':<8} | {'UOM':<6} | {'Price/UOM':<10} | {'Category'}")
        print("-" * 150)
        for u in sorted(usable_list, key=lambda x: x['sku']):
            print(f"{u['sku']:<35} | {u['name'][:35]:<35} | € {u['price_pack']:<8.4f} | {u['pack_qty']:<5} | {u['volume_ml']:<8} | {u['comparison_unit']:<6} | € {u['normalized_price']:<8.4f} | {u['category']}")
            
        print("\n" + "="*80)
        print("5. SIMULAZIONE RESOLVER ORDINE REALE MISTO")
        print("="*80)
        print(f"{'Query Prodotto':<30} | {'SKU Target':<35} | {'Risolto':<8} | {'Fornitore':<12} | {'Prezzo/UOM':<10} | {'Prezzo Pack':<12} | {'Colli'}")
        print("-" * 135)
        for r in resolver_results:
            resolved_str = "SI" if r['resolved'] else "NO"
            supplier_str = r['supplier'] if r['supplier'] else "-"
            price_norm_str = f"€ {r['price_norm']}" if r['price_norm'] else "-"
            price_pack_str = f"€ {r['price_pack']}" if r['price_pack'] else "-"
            packs_str = str(r['packs_needed']) if r['packs_needed'] else "-"
            print(f"{r['query']:<30} | {r['sku']:<35} | {resolved_str:<8} | {supplier_str:<12} | {price_norm_str:<10} | {price_pack_str:<12} | {packs_str}")
            if r['warning']:
                print(f"   ⚠️ WARNING: {r['warning']}")

        print("\n" + "="*80)
        print("6. LISTA PRODOTTI ANCORA ESCLUSI DA LAVORARE")
        print("="*80)
        print(f"A. BRAND MISMATCH ({len(excluded_groups['brand_mismatch'])} righe):")
        for x in excluded_groups['brand_mismatch'][:10]:
            print(f"   - {x}")
        if len(excluded_groups['brand_mismatch']) > 10:
            print(f"   ... e altre {len(excluded_groups['brand_mismatch']) - 10} righe")
            
        print(f"\nB. NO CANDIDATE ({len(excluded_groups['no_candidate'])} righe):")
        for x in excluded_groups['no_candidate'][:10]:
            print(f"   - {x}")
        if len(excluded_groups['no_candidate']) > 10:
            print(f"   ... e altre {len(excluded_groups['no_candidate']) - 10} righe")
            
        print(f"\nC. PRODOTTO MANCANTE A CATALOGO ({len(excluded_groups['prodotto_mancante'])} righe):")
        for x in excluded_groups['prodotto_mancante'][:10]:
            print(f"   - {x}")
        if len(excluded_groups['prodotto_mancante']) > 10:
            print(f"   ... e altre {len(excluded_groups['prodotto_mancante']) - 10} righe")

        print(f"\nD. PACK AMBIGUO / POSSIBILE NUOVO PRODUCT CANONICO:")
        print("   - Birre estere e nazionali (es. HEINEKEN, NASTRO AZZURRO, CORONA) in formati multipli (33cl, 66cl, lattina/vetro)")
        print("   - Succhi di frutta Yoga in gusti mancanti (es. Pera 20cl, Pesca 20cl, Albicocca 20cl)")
        print("   - Amari/liquori mancanti a catalogo (es. Vecchia Romagna, Jägermeister, Averna, Montenegro)")
        print("   - Toniche e bibite di fascia premium (es. Fever Tree Tonic 20cl, San Pellegrino bibite gusti assortiti)")
        
        print("\n" + "="*80)
        print("7. PROPOSTA PROSSIMO BATCH PRIORITARIO")
        print("="*80)
        print("Consigliamo come prossimo batch: **BIRRE (Nazionali & Estere)**.")
        print("Motivazione: Le birre costituiscono una parte rilevante del listino Navas (circa 25 righe tra Heineken, Nastro Azzurro, Corona, Tennent's, Moretti, Ceres, Ichnusa) con una combinazione di vetri a perdere, vetri a rendere e lattine, ad alta movimentazione B2B.")
        print("="*80 + "\n")

if __name__ == "__main__":
    asyncio.run(run_report())
