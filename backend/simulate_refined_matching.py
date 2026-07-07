import asyncio
import os
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product
from app.services.supplier_list_import import import_supplier_list_excel

# I 56 prodotti canonici attivi e approvati (esclusi i 13 REJECT)
approved_products = [
    # 1. ACQUE (9)
    {"sku_interno": "ACQ-LETE-150CL", "canonical_name": "Acqua Lete 1.5 L", "brand": "Lete", "category": "acqua", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-FERRARELLE-50CL", "canonical_name": "Acqua Ferrarelle 50 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-FERRARELLE-75CL", "canonical_name": "Acqua Ferrarelle 75 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-FERRARELLE-100CL", "canonical_name": "Acqua Ferrarelle 100 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-ELECTA-50CL", "canonical_name": "Acqua Electa 50 cl", "brand": "Electa", "category": "acqua", "volume_ml": 500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-ELECTA-75CL", "canonical_name": "Acqua Electa 75 cl", "brand": "Electa", "category": "acqua", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-ELECTA-100CL", "canonical_name": "Acqua Electa 1 L", "brand": "Electa", "category": "acqua", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-SORGESANA-200CL", "canonical_name": "Acqua Sorgesana 2 L", "brand": "Sorgesana", "category": "acqua", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "ACQ-VERA-200CL", "canonical_name": "Acqua Vera 2 L", "brand": "Vera", "category": "acqua", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},

    # 2. SOFT DRINKS - COCA COLA (5)
    {"sku_interno": "SOFT-COCA_COLA_REG-33CL", "canonical_name": "Coca Cola Regular 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-COCA_COLA_ZERO-33CL", "canonical_name": "Coca Cola Zero 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-COCA_COLA_ZERO_CAFF-33CL", "canonical_name": "Coca Cola Zero Caffeina 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-COCA_COLA_REG-200CL", "canonical_name": "Coca Cola Regular 2 L", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-COCA_COLA_ZERO-150CL", "canonical_name": "Coca Cola Zero 1.5 L", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},

    # 3. SOFT DRINKS - FANTA (1)
    {"sku_interno": "SOFT-FANTA_REG-33CL", "canonical_name": "Fanta Regular 33 cl", "brand": "Fanta", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},

    # 4. SOFT DRINKS - SCHWEPPES (6)
    {"sku_interno": "SOFT-SCHWEPPES_TONICA-18CL", "canonical_name": "Schweppes Tonica 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-SCHWEPPES_LIMONE-18CL", "canonical_name": "Schweppes Limone 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-SCHWEPPES_ARANCIA-18CL", "canonical_name": "Schweppes Arancia 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-SCHWEPPES_POMPELMO-100CL", "canonical_name": "Schweppes Pompelmo Rosa 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-SCHWEPPES_TONICA-100CL", "canonical_name": "Schweppes Tonica 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-SCHWEPPES_LIMONE-100CL", "canonical_name": "Schweppes Limone 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},

    # 5. SOFT DRINKS - THOMAS HENRY (1)
    {"sku_interno": "SOFT-THOMAS_HENRY_TONIC-20CL", "canonical_name": "Thomas Henry Tonic 20 cl", "brand": "Thomas Henry", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},

    # 6. SOFT DRINKS - SAN PELLEGRINO & CRODINO (2)
    {"sku_interno": "SOFT-SAN_PELLEGRINO_COCKTAIL_ROSSO-20CL", "canonical_name": "S.Pellegrino Cocktail Rosso 20 cl", "brand": "San Pellegrino", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-CRODINO-17CL", "canonical_name": "Crodino XL 17.5 cl", "brand": "Crodino", "category": "soft_drink", "volume_ml": 175, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},

    # 7. SOFT DRINKS - RED BULL (1)
    {"sku_interno": "SOFT-RED_BULL-25CL", "canonical_name": "Red Bull Energy Drink 25 cl", "brand": "Red Bull", "category": "soft_drink", "volume_ml": 250, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True},

    # 8. SOFT DRINKS - FEVER TREE (3)
    {"sku_interno": "SOFT-FEVER_TREE_TONIC-20CL", "canonical_name": "Fever Tree Indian Tonic 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-FEVER_TREE_ELDERFLOWER-20CL", "canonical_name": "Fever Tree Elderflower Tonic 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-FEVER_TREE_GRAPEFRUIT-20CL", "canonical_name": "Fever Tree Pink Grapefruit 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},

    # 9. SOFT DRINKS - CEDRATA SAN BENEDETTO (1)
    {"sku_interno": "SOFT-CEDRATA_SAN_BENEDETTO-150CL", "canonical_name": "Cedrata San Benedetto 150 cl", "brand": "San Benedetto", "category": "soft_drink", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},

    # 10. SOFT DRINKS - YOGA (9)
    {"sku_interno": "SOFT-YOGA_ACE-20CL", "canonical_name": "Yoga Magic ACE 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_PESCA-20CL", "canonical_name": "Yoga Magic Pesca 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_PERA-20CL", "canonical_name": "Yoga Magic Pera 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_ALBICOCCA-20CL", "canonical_name": "Yoga Magic Albicocca 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_MIRTILLO-20CL", "canonical_name": "Yoga Magic Mirtillo 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_MELA_VERDE-20CL", "canonical_name": "Yoga Magic Mela Verde 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_ACE-100CL", "canonical_name": "Yoga ACE 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_ARANCIA-100CL", "canonical_name": "Yoga Arancia 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},
    {"sku_interno": "SOFT-YOGA_ANANAS-100CL", "canonical_name": "Yoga Ananas 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True},

    # 11. BEVERAGE - SPUMANTI / VINI (9)
    {"sku_interno": "BEV-BELLAVISTA_ALMA-75CL", "canonical_name": "Bellavista Alma Gran Cuvée 75 cl", "brand": "Bellavista", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-BERLUCCHI_61_BRUT-75CL", "canonical_name": "Berlucchi 61 Franciacorta 75 cl", "brand": "Berlucchi", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-FERRARI_MAXIMUM-75CL", "canonical_name": "Ferrari Maximum Blanc de Blancs 75 cl", "brand": "Ferrari", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-FERRARI_BRUT-75CL", "canonical_name": "Ferrari Brut Spumante 75 cl", "brand": "Ferrari", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-MARISA_CUOMO_FURORE_BIANCO-75CL", "canonical_name": "Furore Bianco Cuomo 75 cl", "brand": "Marisa Cuomo", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-MARISA_CUOMO_FIORDUVA_FURORE-75CL", "canonical_name": "Fiorduva Furore Bianco Cuomo 75 cl", "brand": "Marisa Cuomo", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-FEUDI_DI_SAN_GREGORIO_RUBRATO-75CL", "canonical_name": "Rubrato Aglianico Feudi 75 cl", "brand": "Feudi", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-JERMANN_CHARDONNAY-75CL", "canonical_name": "Jermann Chardonnay 75 cl", "brand": "Jermann", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-TERRA_SERENA_GRAND_CUVE-75CL", "canonical_name": "Serena Gran Cuvée Spumante 75 cl", "brand": "Terra Serena", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},

    # 12. BEVERAGE - SPIRITS (9)
    {"sku_interno": "BEV-ABSOLUT_VODKA-70CL", "canonical_name": "Absolut Vodka 70 cl", "brand": "Absolut", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-ABSOLUT_VODKA-100CL", "canonical_name": "Absolut Vodka 1 L", "brand": "Absolut", "category": "beverage", "volume_ml": 1000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-GREY_GOOSE_VODKA-70CL", "canonical_name": "Grey Goose Vodka 70 cl", "brand": "Grey Goose", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-BELVEDERE_VODKA-70CL", "canonical_name": "Belvedere Vodka 70 cl", "brand": "Belvedere", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-ZACAPA_23_RUM-70CL", "canonical_name": "Rum Zacapa 23 Solera 70 cl", "brand": "Zacapa", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-JACK_DANIELS_WHISKEY-100CL", "canonical_name": "Jack Daniel's Tennessee 1 L", "brand": "Jack Daniel's", "category": "beverage", "volume_ml": 1000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-LIMONCELLO-200CL", "canonical_name": "Limoncello di Sorrento 2 L", "brand": "Limoncello", "category": "beverage", "volume_ml": 2000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-GRAPPA_903_BIANCA-70CL", "canonical_name": "Grappa 903 Bianca 70 cl", "brand": "Grappa 903", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False},
    {"sku_interno": "BEV-GRAPPA_903_BARRIQUE-70CL", "canonical_name": "Grappa 903 Barrique 70 cl", "brand": "Grappa 903", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False}
]

async def simulate():
    filepath = "data/import_samples/storico_prezzi_navas.xlsx"
    with open(filepath, "rb") as f:
        file_bytes = f.read()
        
    async with async_session_factory() as db:
        # Inserisci temporaneamente i prodotti per isolare il dry_run
        async with db.begin():
            # Cancella i prodotti appena inseriti nel DB reale per questa sessione di test simulata,
            # oppure usa direttamente la transazione per farne rollback.
            # In questo caso, visto che abbiamo già inserito nel DB i nuovi prodotti attivi con apply-new-only,
            # il database reale contiene già i 29 nuovi prodotti inseriti.
            # Ma gli altri prodotti (esistenti o conflitti) sono già presenti nel DB reale.
            # Quindi l'importazione excel interrogherà direttamente i prodotti nel database reale.
            
            # Esegui l'importazione Excel in modalità dry_run
            res = await import_supplier_list_excel(
                db=db, 
                supplier_id=11, 
                file_bytes=file_bytes, 
                dry_run=True
            )
            
            # Raggruppa i risultati reali del motore di scoring
            preview = res.get("preview", [])
            
            score_ge_90 = 0
            score_70_89 = 0
            score_under_70 = 0
            
            detail_matches = []
            
            for p in preview:
                score = p.get("score", 0.0)
                raw_desc = p.get("raw_description")
                decision = p.get("decision")
                
                if score >= 90.0:
                    score_ge_90 += 1
                    detail_matches.append((p["row_index"], raw_desc, p.get("matched_sku") or "Auto-Match Recommended", score, decision))
                elif 70.0 <= score < 90.0:
                    score_70_89 += 1
                    detail_matches.append((p["row_index"], raw_desc, "Parking Recommended", score, decision))
                else:
                    score_under_70 += 1
                    
            print("=== NUOVA STIMA DI MATCH SUL LISTINO NAVAS ===")
            print(f"Righe totali con prezzo: {len(preview)}")
            print(f"Match probabili ad alta confidenza (score >= 90%): {score_ge_90}")
            print(f"Match in Parking Area moderati (score 70-89%): {score_70_89}")
            print(f"Nessun match / Score basso (score < 70%): {score_under_70}")
            print("-----------------------------------------------------")
            print("Esempi di match rilevati dal motore (Top 40 per score):")
            for m in sorted(detail_matches, key=lambda x: x[3], reverse=True)[:40]:
                print(f"  * Riga {m[0]} | {m[1]} -> Match: {m[2]} (Score: {m[3]:.1f}%, Dec: {m[4]})")
            
            # Rollback per evitare di scrivere nulla da questo dry-run
            await db.rollback()

if __name__ == "__main__":
    asyncio.run(simulate())
