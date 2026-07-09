import openpyxl
from collections import defaultdict
from app.services.normalization import extract_volume_ml

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

def run_exclusions():
    wb = openpyxl.load_workbook("data/import_samples/storico_prezzi_navas.xlsx", data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    data_rows = rows[5:]
    
    reasons = defaultdict(list)
    for idx, r in enumerate(data_rows):
        row_num = idx + 6
        desc = str(r[1]) if r[1] is not None else ""
        price = r[2]
        
        # 1. Servizio / PFA / Prezzo non valido
        if not desc or price is None or str(price).strip() in ("VED ALL", "N.D.", "-", "VEDI ALLEGATO", ""):
            reasons["Servizio / voce non prodotto o prezzo assente (es. PFA, note)"].append((row_num, desc))
            continue
            
        # Check family
        matched_family = None
        for f in families:
            if any(k in desc.lower() for k in f["keywords"]):
                matched_family = f
                break
                
        if not matched_family:
            reasons["Prodotto non prioritario (es. Birre Ceres/Corona/Heineken, liquori Abaca/Amara/Jefferson)"].append((row_num, desc))
            continue
            
        volume = extract_volume_ml(desc)
        if not volume:
            if "1 litro" in desc.lower() or "1litro" in desc.lower() or "1 lt" in desc.lower() or "1lt" in desc.lower():
                volume = 1000
            elif "2 lt" in desc.lower() or "2lt" in desc.lower() or "2 litri" in desc.lower():
                volume = 2000
                
        if not volume:
            reasons["Troppo ambigue / Brand o formato non chiaro (volume o peso non identificato)"].append((row_num, desc))
            continue
            
    for reason, items in reasons.items():
        print(f"=== {reason} ({len(items)} righe) ===")
        for item in items[:15]:
            print(f"  * Riga {item[0]}: {item[1]}")
        print()

if __name__ == "__main__":
    run_exclusions()
