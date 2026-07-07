import asyncio
import argparse
from sqlalchemy import select
from app.database import async_session_factory
from app.models.products import Product

# Definizioni dei 69 prodotti canonici proposti con status iniziale
refined_products = [
    # 1. ACQUE (9)
    {"sku_interno": "ACQ-LETE-150CL", "canonical_name": "Acqua Lete 1.5 L", "brand": "Lete", "category": "acqua", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-FERRARELLE-50CL", "canonical_name": "Acqua Ferrarelle 50 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-FERRARELLE-75CL", "canonical_name": "Acqua Ferrarelle 75 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-FERRARELLE-100CL", "canonical_name": "Acqua Ferrarelle 100 cl", "brand": "Ferrarelle", "category": "acqua", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-ELECTA-50CL", "canonical_name": "Acqua Electa 50 cl", "brand": "Electa", "category": "acqua", "volume_ml": 500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-ELECTA-75CL", "canonical_name": "Acqua Electa 75 cl", "brand": "Electa", "category": "acqua", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-ELECTA-100CL", "canonical_name": "Acqua Electa 1 L", "brand": "Electa", "category": "acqua", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-SORGESANA-200CL", "canonical_name": "Acqua Sorgesana 2 L", "brand": "Sorgesana", "category": "acqua", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "ACQ-VERA-200CL", "canonical_name": "Acqua Vera 2 L", "brand": "Vera", "category": "acqua", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 2. SOFT DRINKS - COCA COLA (7)
    {"sku_interno": "SOFT-COCA_COLA_REG-33CL", "canonical_name": "Coca Cola Regular 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-COCA_COLA_ZERO-33CL", "canonical_name": "Coca Cola Zero 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-COCA_COLA_ZERO_CAFF-33CL", "canonical_name": "Coca Cola Zero Caffeina 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-COCA_COLA_REG-200CL", "canonical_name": "Coca Cola Regular 2 L", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 2000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-COCA_COLA_ZERO-150CL", "canonical_name": "Coca Cola Zero 1.5 L", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Lattine standard senza riga Navas reale -> REJECT
    {"sku_interno": "SOFT-COCA_COLA_LATTINA-33CL", "canonical_name": "Coca Cola Regular Lattina 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-COCA_COLA_ZERO_LATTINA-33CL", "canonical_name": "Coca Cola Zero Lattina 33 cl", "brand": "Coca Cola", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},

    # 3. SOFT DRINKS - FANTA / SPRITE (3)
    {"sku_interno": "SOFT-FANTA_REG-33CL", "canonical_name": "Fanta Regular 33 cl", "brand": "Fanta", "category": "soft_drink", "volume_ml": 330, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Fanta e Sprite Lattine standard senza riga Navas reale -> REJECT
    {"sku_interno": "SOFT-FANTA_LATTINA-33CL", "canonical_name": "Fanta Lattina 33 cl", "brand": "Fanta", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-SPRITE_LATTINA-33CL", "canonical_name": "Sprite Lattina 33 cl", "brand": "Sprite", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},

    # 4. SOFT DRINKS - SCHWEPPES (6)
    {"sku_interno": "SOFT-SCHWEPPES_TONICA-18CL", "canonical_name": "Schweppes Tonica 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-SCHWEPPES_LIMONE-18CL", "canonical_name": "Schweppes Limone 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-SCHWEPPES_ARANCIA-18CL", "canonical_name": "Schweppes Arancia 18 cl", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 180, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-SCHWEPPES_POMPELMO-100CL", "canonical_name": "Schweppes Pompelmo Rosa 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-SCHWEPPES_TONICA-100CL", "canonical_name": "Schweppes Tonica 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-SCHWEPPES_LIMONE-100CL", "canonical_name": "Schweppes Limone 1 L", "brand": "Schweppes", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 5. SOFT DRINKS - THOMAS HENRY (3)
    {"sku_interno": "SOFT-THOMAS_HENRY_TONIC-20CL", "canonical_name": "Thomas Henry Tonic 20 cl", "brand": "Thomas Henry", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Thomas Henry non Navas -> REJECT
    {"sku_interno": "SOFT-THOMAS_HENRY_GINGER-20CL", "canonical_name": "Thomas Henry Ginger Beer 20 cl", "brand": "Thomas Henry", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-THOMAS_HENRY_PINK-20CL", "canonical_name": "Thomas Henry Pink Grapefruit 20 cl", "brand": "Thomas Henry", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},

    # 6. SOFT DRINKS - SAN PELLEGRINO & CRODINO (6)
    # OBIETTIVO 5: San Pellegrino analcolici senza riga Navas reale -> REJECT
    {"sku_interno": "SOFT-SAN_PELLEGRINO_BITTER_BIANCO-10CL", "canonical_name": "S.Pellegrino Bitter Bianco 10 cl", "brand": "San Pellegrino", "category": "soft_drink", "volume_ml": 100, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-SAN_PELLEGRINO_BITTER_ROSSO-10CL", "canonical_name": "S.Pellegrino Bitter Rosso 10 cl", "brand": "San Pellegrino", "category": "soft_drink", "volume_ml": 100, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-SAN_PELLEGRINO_COCKTAIL_BIANCO-20CL", "canonical_name": "S.Pellegrino Cocktail Bianco 20 cl", "brand": "San Pellegrino", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-SAN_PELLEGRINO_COCKTAIL_ROSSO-20CL", "canonical_name": "S.Pellegrino Cocktail Rosso 20 cl", "brand": "San Pellegrino", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Crodino 10cl standard senza riga Navas -> REJECT
    {"sku_interno": "SOFT-CRODINO-10CL", "canonical_name": "Crodino 10 cl", "brand": "Crodino", "category": "soft_drink", "volume_ml": 100, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-CRODINO-17CL", "canonical_name": "Crodino XL 17.5 cl", "brand": "Crodino", "category": "soft_drink", "volume_ml": 175, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 7. SOFT DRINKS - RED BULL & ESTATHE (3)
    {"sku_interno": "SOFT-RED_BULL-25CL", "canonical_name": "Red Bull Energy Drink 25 cl", "brand": "Red Bull", "category": "soft_drink", "volume_ml": 250, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Estathé senza riga Navas -> REJECT
    {"sku_interno": "SOFT-ESTATHE_LIMONE-33CL", "canonical_name": "Estathé Limone 33 cl", "brand": "Estathé", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-ESTATHE_PESCA-33CL", "canonical_name": "Estathé Pesca 33 cl", "brand": "Estathé", "category": "soft_drink", "volume_ml": 330, "container_type": "lattina", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},

    # 8. SOFT DRINKS - FEVER TREE (3)
    {"sku_interno": "SOFT-FEVER_TREE_TONIC-20CL", "canonical_name": "Fever Tree Indian Tonic 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-FEVER_TREE_ELDERFLOWER-20CL", "canonical_name": "Fever Tree Elderflower Tonic 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-FEVER_TREE_GRAPEFRUIT-20CL", "canonical_name": "Fever Tree Pink Grapefruit 20 cl", "brand": "Fever Tree", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 9. SOFT DRINKS - CEDRATA SAN BENEDETTO (1)
    {"sku_interno": "SOFT-CEDRATA_SAN_BENEDETTO-150CL", "canonical_name": "Cedrata San Benedetto 150 cl", "brand": "San Benedetto", "category": "soft_drink", "volume_ml": 1500, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 10. SOFT DRINKS - YOGA (10)
    {"sku_interno": "SOFT-YOGA_ACE-20CL", "canonical_name": "Yoga Magic ACE 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_PESCA-20CL", "canonical_name": "Yoga Magic Pesca 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_PERA-20CL", "canonical_name": "Yoga Magic Pera 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_ALBICOCCA-20CL", "canonical_name": "Yoga Magic Albicocca 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    # OBIETTIVO 5: Yoga Ananas 20cl senza riga Navas -> REJECT
    {"sku_interno": "SOFT-YOGA_ANANAS-20CL", "canonical_name": "Yoga Magic Ananas 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "REJECT"},
    {"sku_interno": "SOFT-YOGA_MIRTILLO-20CL", "canonical_name": "Yoga Magic Mirtillo 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_MELA_VERDE-20CL", "canonical_name": "Yoga Magic Mela Verde 20 cl", "brand": "Yoga", "category": "soft_drink", "volume_ml": 200, "container_type": "vetro", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_ACE-100CL", "canonical_name": "Yoga ACE 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_ARANCIA-100CL", "canonical_name": "Yoga Arancia 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},
    {"sku_interno": "SOFT-YOGA_ANANAS-100CL", "canonical_name": "Yoga Ananas 1 L", "brand": "Yoga", "category": "soft_drink", "volume_ml": 1000, "container_type": "pet", "comparison_unit": "liter", "is_commodity": True, "status": "APPROVE"},

    # 11. BEVERAGE - SPUMANTI / VINI (9)
    {"sku_interno": "BEV-BELLAVISTA_ALMA-75CL", "canonical_name": "Bellavista Alma Gran Cuvée 75 cl", "brand": "Bellavista", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-BERLUCCHI_61_BRUT-75CL", "canonical_name": "Berlucchi 61 Franciacorta 75 cl", "brand": "Berlucchi", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-FERRARI_MAXIMUM-75CL", "canonical_name": "Ferrari Maximum Blanc de Blancs 75 cl", "brand": "Ferrari", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-FERRARI_BRUT-75CL", "canonical_name": "Ferrari Brut Spumante 75 cl", "brand": "Ferrari", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-MARISA_CUOMO_FURORE_BIANCO-75CL", "canonical_name": "Furore Bianco Cuomo 75 cl", "brand": "Marisa Cuomo", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-MARISA_CUOMO_FIORDUVA_FURORE-75CL", "canonical_name": "Fiorduva Furore Bianco Cuomo 75 cl", "brand": "Marisa Cuomo", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-FEUDI_DI_SAN_GREGORIO_RUBRATO-75CL", "canonical_name": "Rubrato Aglianico Feudi 75 cl", "brand": "Feudi", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-JERMANN_CHARDONNAY-75CL", "canonical_name": "Jermann Chardonnay 75 cl", "brand": "Jermann", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-TERRA_SERENA_GRAND_CUVE-75CL", "canonical_name": "Serena Gran Cuvée Spumante 75 cl", "brand": "Terra Serena", "category": "beverage", "volume_ml": 750, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},

    # 12. BEVERAGE - SPIRITS (9)
    {"sku_interno": "BEV-ABSOLUT_VODKA-70CL", "canonical_name": "Absolut Vodka 70 cl", "brand": "Absolut", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-ABSOLUT_VODKA-100CL", "canonical_name": "Absolut Vodka 1 L", "brand": "Absolut", "category": "beverage", "volume_ml": 1000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-GREY_GOOSE_VODKA-70CL", "canonical_name": "Grey Goose Vodka 70 cl", "brand": "Grey Goose", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-BELVEDERE_VODKA-70CL", "canonical_name": "Belvedere Vodka 70 cl", "brand": "Belvedere", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-ZACAPA_23_RUM-70CL", "canonical_name": "Rum Zacapa 23 Solera 70 cl", "brand": "Zacapa", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-JACK_DANIELS_WHISKEY-100CL", "canonical_name": "Jack Daniel's Tennessee 1 L", "brand": "Jack Daniel's", "category": "beverage", "volume_ml": 1000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-LIMONCELLO-200CL", "canonical_name": "Limoncello di Sorrento 2 L", "brand": "Limoncello", "category": "beverage", "volume_ml": 2000, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-GRAPPA_903_BIANCA-70CL", "canonical_name": "Grappa 903 Bianca 70 cl", "brand": "Grappa 903", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"},
    {"sku_interno": "BEV-GRAPPA_903_BARRIQUE-70CL", "canonical_name": "Grappa 903 Barrique 70 cl", "brand": "Grappa 903", "category": "beverage", "volume_ml": 700, "container_type": "vetro", "comparison_unit": "bottle", "is_commodity": False, "status": "APPROVE"}
]

async def run_bootstrap(mode: str):
    print("=== INIZIO PROCESSO DI BOOTSTRAP CANONICO ===")
    print(f"Modalità: {mode.upper()}")
    print(f"Prodotti proposti totali: {len(refined_products)}")

    # Filtra i prodotti reject a monte
    active_proposals = [p for p in refined_products if p["status"] == "APPROVE"]
    rejected_proposals = [p for p in refined_products if p["status"] == "REJECT"]
    print(f"Prodotti esclusi/REJECT a monte (senza Navas collegate): {len(rejected_proposals)}")
    print(f"Prodotti attivi da valutare: {len(active_proposals)}\n")

    new_products_to_insert = []
    existing_products_skipped = []
    conflicts_to_review = []

    async with async_session_factory() as db:
        # Avvia transazione esplicita
        async with db.begin():
            for p_dict in active_proposals:
                sku = p_dict["sku_interno"]
                
                # Cerca sku
                stmt = select(Product).where(Product.sku_interno == sku)
                existing_product = (await db.execute(stmt)).scalars().first()

                if not existing_product:
                    # Nuovo prodotto
                    new_products_to_insert.append(sku)
                    if mode in ("apply", "apply-new-only"):
                        new_prod = Product(
                            sku_interno=sku,
                            canonical_name=p_dict["canonical_name"],
                            brand=p_dict["brand"],
                            category=p_dict["category"],
                            volume_ml=p_dict["volume_ml"],
                            container_type=p_dict["container_type"],
                            comparison_unit=p_dict["comparison_unit"],
                            is_commodity=p_dict["is_commodity"],
                            is_active=True
                        )
                        db.add(new_prod)
                        print(f"[NUOVO - INSERITO] {sku}: {p_dict['canonical_name']}")
                    else:
                        print(f"[NUOVO - DA INSERIRE] {sku}: {p_dict['canonical_name']}")
                else:
                    # Già esistente, controlla differenze
                    diffs = []
                    fields_to_check = ["canonical_name", "brand", "category", "volume_ml", "container_type", "comparison_unit", "is_commodity"]
                    for field in fields_to_check:
                        db_val = getattr(existing_product, field)
                        prop_val = p_dict[field]
                        if db_val != prop_val:
                            diffs.append(f"{field}: DB='{db_val}' vs NUOV='{prop_val}'")

                    if not diffs:
                        existing_products_skipped.append(sku)
                        print(f"[ESISTENTE - SALTATO] {sku} è identico.")
                    else:
                        conflicts_to_review.append((sku, diffs))
                        print(f"[CONFLITTO - SALTATO] {sku} ha campi differenti:")
                        for d in diffs:
                            print(f"  * {d}")

            # Se dry-run, facciamo rollback esplicito
            if mode == "dry-run":
                print("\n[INFO] Dry-run attivo: eseguo ROLLBACK automatico della transazione.")
                await db.rollback()

    # Stampa report finale
    print("\n================ REPORT BOOTSTRAP ================")
    print(f"Proposti totali:             {len(refined_products)}")
    print(f"Esclusi a monte (REJECT):    {len(rejected_proposals)}")
    print(f"Nuovi da inserire/inseriti:  {len(new_products_to_insert)}")
    print(f"Esistenti identici saltati:   {len(existing_products_skipped)}")
    print(f"Conflitti saltati:           {len(conflicts_to_review)}")
    print("==================================================")
    
    if mode == "dry-run":
        print("\nElenco dei nuovi prodotti da inserire:")
        for sku in new_products_to_insert:
            p_ref = next(p for p in active_proposals if p["sku_interno"] == sku)
            print(f"  - {sku} | {p_ref['canonical_name']} ({p_ref['category']})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Beverage Catalog Bootstrap Script (Selective)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Mostra cosa verrebbe inserito senza modificare il DB")
    group.add_argument("--apply", action="store_true", help="Applica le modifiche globali (nuovi + aggiorna)")
    group.add_argument("--apply-new-only", action="store_true", help="Applica SOLO i nuovi prodotti non in conflitto")
    args = parser.parse_args()

    mode_str = "dry-run"
    if args.apply:
        mode_str = "apply"
    elif args.apply_new_only:
        mode_str = "apply-new-only"

    asyncio.run(run_bootstrap(mode_str))
