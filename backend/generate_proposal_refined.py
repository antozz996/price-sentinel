import openpyxl
import re
import json
from collections import defaultdict, Counter
from app.services.normalization import normalize_text, extract_volume_ml, infer_category, extract_pack_qty
def slugify(text: str) -> str:
    s = text.upper().replace(" ", "_").replace("'", "").replace(".", "").replace("-", "_")
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def run_refinement():
    wb = openpyxl.load_workbook("data/import_samples/storico_prezzi_navas.xlsx", data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    
    header_idx = 4
    data_rows = rows[header_idx + 1:]
    
    # Definiamo le regole delle famiglie di prodotti
    families = [
        # 1. ACQUE
        {"name": "Ferrarelle", "cat": "acqua", "keywords": ["ferrarelle"]},
        {"name": "Sorgesana", "cat": "acqua", "keywords": ["sorgesana"]},
        {"name": "Electa", "cat": "acqua", "keywords": ["electa"]},
        {"name": "Vera", "cat": "acqua", "keywords": ["vera"]},
        {"name": "Lete", "cat": "acqua", "keywords": ["lete"]},
        {"name": "San Benedetto", "cat": "acqua", "keywords": ["san benedetto", "s.benedetto"]},
        {"name": "Panna", "cat": "acqua", "keywords": ["panna"]},
        {"name": "Perrier", "cat": "acqua", "keywords": ["perrier"]},
        
        # 2. COCA COLA / FANTA / SPRITE
        {"name": "Coca Cola", "cat": "soft_drink", "keywords": ["coca cola", "coca-cola", "coca"]},
        {"name": "Fanta", "cat": "soft_drink", "keywords": ["fanta"]},
        {"name": "Sprite", "cat": "soft_drink", "keywords": ["sprite"]},
        
        # 3. SCHWEPPES
        {"name": "Schweppes", "cat": "soft_drink", "keywords": ["schweppes"]},
        
        # 4. SAN PELLEGRINO BITTER / COCKTAIL
        {"name": "San Pellegrino", "cat": "soft_drink", "keywords": ["s.pellegrino", "s. pellegrino", "san pellegrino"]},
        
        # 5. CRODINO
        {"name": "Crodino", "cat": "soft_drink", "keywords": ["crodino"]},
        
        # 6. RED BULL / ENERGY DRINKS
        {"name": "Red Bull", "cat": "soft_drink", "keywords": ["red bull", "redbull"]},
        
        # 7. ESTATHE
        {"name": "Estathe", "cat": "soft_drink", "keywords": ["estathe", "estathe'"]},
        
        # 8. YOGA SUCCHI
        {"name": "Yoga", "cat": "beverage", "keywords": ["yoga"]},
        
        # 9. THOMAS HENRY
        {"name": "Thomas Henry", "cat": "soft_drink", "keywords": ["thomas henry", "thomas h.", "thomas h"]},
        
        # 10. FEVER TREE
        {"name": "Fever Tree", "cat": "soft_drink", "keywords": ["fever tree", "fever-tree"]},
        
        # 11. VINI / SPUMANTI
        {"name": "Bellavista", "cat": "beverage", "keywords": ["bellavista"]},
        {"name": "Berlucchi", "cat": "beverage", "keywords": ["berlucchi"]},
        {"name": "Ferrari", "cat": "beverage", "keywords": ["ferrari"]},
        {"name": "Terra Serena", "cat": "beverage", "keywords": ["terra serena", "serena"]},
        {"name": "Marisa Cuomo", "cat": "beverage", "keywords": ["marisa cuomo", "furore", "fiorduva"]},
        {"name": "Feudi di San Gregorio", "cat": "beverage", "keywords": ["feudi di san gregorio", "feudi aglianico", "feudi rubrato"]},
        {"name": "Jermann", "cat": "beverage", "keywords": ["jermann", "chardonnay jermann"]},
        
        # 12. SPIRITS / LIQUORI / GRAPPE
        {"name": "Limoncello", "cat": "beverage", "keywords": ["limoncello"]},
        {"name": "Grappa 903", "cat": "beverage", "keywords": ["grappa 903", "903 barrique", "903"]},
        {"name": "Absolut", "cat": "beverage", "keywords": ["absolut"]},
        {"name": "Havana", "cat": "beverage", "keywords": ["havana"]},
        {"name": "Pampero", "cat": "beverage", "keywords": ["pampero"]},
        {"name": "Jack Daniel's", "cat": "beverage", "keywords": ["jack daniel", "jack daniels"]},
        {"name": "Zacapa", "cat": "beverage", "keywords": ["zacapa"]},
        {"name": "Belvedere", "cat": "beverage", "keywords": ["belvedere"]},
        {"name": "Grey Goose", "cat": "beverage", "keywords": ["grey goose"]},
        {"name": "Hendrick's", "cat": "beverage", "keywords": ["hendrick", "hendricks", "hendrick's"]},
        {"name": "Bombay", "cat": "beverage", "keywords": ["bombay"]},
        {"name": "Tanqueray", "cat": "beverage", "keywords": ["tanqueray"]},
        {"name": "Gin Mare", "cat": "beverage", "keywords": ["gin mare"]},
        {"name": "Aperol", "cat": "beverage", "keywords": ["aperol"]},
        {"name": "Campari", "cat": "beverage", "keywords": ["campari"]},
        {"name": "Montenegro", "cat": "beverage", "keywords": ["montenegro"]},
        {"name": "Averna", "cat": "beverage", "keywords": ["averna"]},
        {"name": "Vecchia Romagna", "cat": "beverage", "keywords": ["vecchia romagna"]},
        {"name": "Disaronno", "cat": "beverage", "keywords": ["disaronno", "amaretto disaronno"]}
    ]
    
    proposed_groups = defaultdict(list)
    excluded_rows = []
    
    for idx, row in enumerate(data_rows):
        row_num = idx + header_idx + 2
        if not any(cell is not None for cell in row):
            continue
            
        sku_forn = str(row[0]).strip() if row[0] is not None else ""
        raw_desc = str(row[1]).strip() if row[1] is not None else ""
        price_raw = row[2]
        
        # Gestione prezzi speciali
        if not raw_desc or price_raw is None or str(price_raw).strip() in ("VED ALL", "N.D.", "-", "VEDI ALLEGATO", ""):
            excluded_rows.append((row_num, raw_desc, "Prezzo non valido o assente"))
            continue
            
        norm_desc = raw_desc.lower()
        
        # Cerca la famiglia corrispondente
        matched_family = None
        for f in families:
            if any(k in norm_desc for k in f["keywords"]):
                matched_family = f
                break
                
        if not matched_family:
            excluded_rows.append((row_num, raw_desc, "Nessuna delle famiglie prioritare individuate"))
            continue
            
        # Estrai il volume
        volume_ml = extract_volume_ml(raw_desc)
        # Se non viene estratto direttamente ma c'è scritto 1 LITRO o 1LITRO, fallback
        if not volume_ml:
            if "1 litro" in norm_desc or "1litro" in norm_desc or "1 lt" in norm_desc or "1lt" in norm_desc:
                volume_ml = 1000
            elif "2 lt" in norm_desc or "2lt" in norm_desc or "2 litri" in norm_desc:
                volume_ml = 2000
            elif "1.5 lt" in norm_desc or "1.5lt" in norm_desc or "1.5 litri" in norm_desc:
                volume_ml = 1500
                
        if not volume_ml:
            excluded_rows.append((row_num, raw_desc, "Volume non identificabile"))
            continue
            
        pack_qty = extract_pack_qty(raw_desc) or 1
        
        # Raggruppa per famiglia, volume e categoria
        group_key = (matched_family["name"], volume_ml, matched_family["cat"])
        proposed_groups[group_key].append({
            "row_num": row_num,
            "sku_forn": sku_forn,
            "raw_desc": raw_desc,
            "price": price_raw,
            "pack_qty": pack_qty
        })
        
    proposals = []
    
    for (brand_name, volume, cat), examples in proposed_groups.items():
        brand_slug = slugify(brand_name)
        volume_cl = volume // 10
        
        # Determina prefisso SKU
        if cat == "acqua":
            prefix = "ACQ"
            comp_unit = "liter"
            is_commodity = True
        elif cat == "soft_drink":
            prefix = "BEV"
            comp_unit = "liter"
            is_commodity = True
        else:
            prefix = "BEV"
            comp_unit = "bottle"
            is_commodity = False
            
        sku = f"{prefix}-{brand_slug}-{volume_cl}CL"
        
        # Nome canonico
        if cat == "acqua":
            canonical_name = f"Acqua {brand_name} {volume_cl} cl"
        else:
            canonical_name = f"{brand_name} {volume_cl} cl"
            
        # Determina container_type
        container = "vetro"
        all_desc_lower = "".join([e["raw_desc"].lower() for e in examples])
        if "pet" in all_desc_lower or "lattina" in all_desc_lower or "sleek" in all_desc_lower or "latt" in all_desc_lower:
            if "latt" in all_desc_lower or "sleek" in all_desc_lower:
                container = "lattina"
            else:
                container = "pet"
        elif "vap" in all_desc_lower or "var" in all_desc_lower or "vetro" in all_desc_lower:
            container = "vetro"
            
        motivation = f"Referenza standard {brand_name} formato {volume_cl} cl (copre {len(examples)} righe nel listino Navas)"
        
        proposals.append({
            "sku_interno": sku,
            "canonical_name": canonical_name,
            "brand": brand_name,
            "category": cat,
            "volume_ml": volume,
            "weight_g": None,
            "container_type": container,
            "comparison_unit": comp_unit,
            "is_commodity": is_commodity,
            "motivazione": motivation,
            "esempi_righe_navas": [f"Riga {e['row_num']}: {e['raw_desc']} (Codice: {e['sku_forn']})" for e in examples]
        })
        
    proposals.sort(key=lambda x: (x["category"], x["brand"], x["volume_ml"]))
    
    # Scrive l'output in JSON per verifica
    output_data = {
        "proposals": proposals,
        "excluded_count": len(excluded_rows),
        "excluded_samples": excluded_rows[:20]
    }
    
    with open("data/import_samples/beverage_canonical_bootstrap.json", "w") as out:
        json.dump(output_data, out, indent=2)
        
    print(f"Righe totali lette: {len(data_rows)}")
    print(f"Prodotti canonici proposti: {len(proposals)}")
    print(f"Righe coperte da proposte: {sum(len(v) for v in proposed_groups.values())}")
    print(f"Righe escluse: {len(excluded_rows)}")
    
if __name__ == "__main__":
    run_refinement()
