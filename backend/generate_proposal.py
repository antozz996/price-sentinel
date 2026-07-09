import asyncio
import json
import re
import openpyxl
from collections import defaultdict
from app.services.normalization import normalize_text, extract_volume_ml, infer_category, extract_pack_qty

def slugify(text: str) -> str:
    s = text.upper().replace(" ", "_").replace("'", "").replace(".", "").replace("-", "_")
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def run_proposal():
    wb = openpyxl.load_workbook("data/import_samples/storico_prezzi_navas.xlsx", data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    
    # Header is at row 4
    header_idx = 4
    data_rows = rows[header_idx + 1:]
    
    proposed_groups = defaultdict(list)
    excluded_rows = []
    
    for idx, row in enumerate(data_rows):
        row_num = idx + header_idx + 2
        if not any(cell is not None for cell in row):
            continue
            
        sku_forn = str(row[0]).strip() if row[0] is not None else ""
        raw_desc = str(row[1]).strip() if row[1] is not None else ""
        price = row[2]
        
        if not raw_desc or price is None or str(price).strip() in ("VED ALL", "N.D.", "-", "VEDI ALLEGATO", ""):
            excluded_rows.append((row_num, raw_desc, "Prezzo non valido o assente"))
            continue
            
        # Normalizzazioni
        norm_desc = normalize_text(raw_desc)
        volume_ml = extract_volume_ml(raw_desc)
        category = infer_category(raw_desc)
        pack_qty = extract_pack_qty(raw_desc) or 1
        
        # Estrai Brand (regola euristica)
        brand = None
        for b in ["coca cola", "fanta", "sprite", "schweppes", "s.pellegrino", "s. pellegrino", "crodino", "red bull", "estathe", "yoga", "thomas henry", "fever tree", "ferrarelle", "sorgesana", "electa", "vera", "lete", "san benedetto", "uliveto", "rocchetta", "perrier", "spumador", "tassoni"]:
            if b in norm_desc:
                brand = b
                break
                
        # Fallback brand: prima parola se alcolico/vino/spirits
        if not brand and category in ("beverage", "spirits", "vino"):
            # Prova a estrarre brand da parole note di vini o liquori
            for b in ["bellavista", "marisa cuomo", "st michael-eppan", "ferrari", "terra serena", "903 barrique", "keglevich", "absolut", "havana", "pampero", "jack daniel", "jameson", "tanqueray", "bombay", "campari", "aperol", "baileys", "disaronno"]:
                if b in norm_desc:
                    brand = b
                    break
            if not brand:
                words = [w for w in norm_desc.split() if len(w) > 3]
                if words:
                    brand = words[0]
                    
        if not brand:
            excluded_rows.append((row_num, raw_desc, "Brand non identificabile con certezza"))
            continue
            
        if not volume_ml:
            excluded_rows.append((row_num, raw_desc, "Volume non identificato"))
            continue
            
        # Chiave di raggruppamento
        group_key = (brand.lower(), volume_ml, category)
        proposed_groups[group_key].append({
            "row_num": row_num,
            "sku_forn": sku_forn,
            "raw_desc": raw_desc,
            "price": price,
            "pack_qty": pack_qty
        })
        
    print(f"Righe totali processate: {len(data_rows)}")
    print(f"Righe incluse per proposta: {sum(len(v) for v in proposed_groups.values())}")
    print(f"Righe escluse: {len(excluded_rows)}")
    
    # Genera la lista dei Product proposti
    proposals = []
    
    # Traduzione categorie
    cat_mapping = {
        "acqua": "acqua",
        "soft_drink": "soft_drink",
        "beverage": "beverage",
        "monouso": "monouso"
    }
    
    for (brand, volume, category), examples in proposed_groups.items():
        # Costruisci SKU canonico
        brand_slug = slugify(brand)
        volume_cl = volume // 10
        
        # Prefisso SKU
        prefix = "ACQ" if category == "acqua" else "BEV"
        sku = f"{prefix}-{brand_slug}-{volume_cl}CL"
        
        # Nome canonico
        canonical_name = f"{brand.title()} {volume_cl} cl"
        if category == "acqua":
            canonical_name = f"Acqua {brand.title()} {volume_cl} cl"
            comp_unit = "liter"
        elif category == "soft_drink":
            comp_unit = "liter"
        else:
            comp_unit = "bottle"
            
        is_commodity = category in ("acqua", "soft_drink")
        
        # Motivazione
        motivation = f"Referenza standard {brand.title()} in formato {volume_cl} cl, adatta a coprire {len(examples)} riga/he del listino Navas."
        
        proposals.append({
            "sku_interno": sku,
            "canonical_name": canonical_name,
            "brand": brand.title(),
            "category": cat_mapping.get(category, "beverage"),
            "volume_ml": volume,
            "weight_g": None,
            "container_type": "vetro" if "vetro" in "".join([e["raw_desc"].lower() for e in examples]) or "vr" in "".join([e["raw_desc"].lower() for e in examples]) else "pet",
            "comparison_unit": comp_unit,
            "is_commodity": is_commodity,
            "motivazione": motivation,
            "esempi_righe_navas": [f"Riga {e['row_num']}: {e['raw_desc']} (Codice: {e['sku_forn']})" for e in examples]
        })
        
    # Ordiniamo le proposte per categoria e poi per brand
    proposals.sort(key=lambda x: (x["category"], x["brand"]))
    
    # Stampa in formato Markdown/JSON
    print("\nPROPOSTA PRODOTTI CANONICI:")
    print(json.dumps(proposals[:60], indent=2))
    
    # Categorie count
    counts = Counter([p["category"] for p in proposals])
    print("\nConteggi Categorie Proposte:")
    for c, cnt in counts.items():
        print(f"  - {c}: {cnt}")
        
    print("\nRighe escluse (Esempi):")
    for r in excluded_rows[:15]:
        print(f"  Riga {r[0]} | {r[1]} | Motivo: {r[2]}")

if __name__ == "__main__":
    from collections import Counter
    run_proposal()
