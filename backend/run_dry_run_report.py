import asyncio
import json
import os
import sys
from decimal import Decimal
from datetime import date, datetime
from collections import Counter
from sqlalchemy import select
from app.database import async_session_factory
from app.services.supplier_list_import import import_supplier_list_excel

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)

async def generate_report():
    supplier_id = 11  # Navas Srl
    filepath = "data/import_samples/storico_prezzi_navas.xlsx"
    
    if not os.path.exists(filepath):
        print(f"Errore: Il file {filepath} non esiste.")
        sys.exit(1)
        
    with open(filepath, "rb") as f:
        file_bytes = f.read()
        
    async with async_session_factory() as db:
        # Esegui l'importazione in modalità dry_run
        res = await import_supplier_list_excel(
            db=db, 
            supplier_id=supplier_id, 
            file_bytes=file_bytes, 
            dry_run=True
        )
        
    preview = res.get("preview", [])
    errori_parsing = res.get("errori_parsing", [])
    
    righe_totali = res["righe_totali_lette"]
    righe_con_prezzo = len(preview)
    righe_senza_prezzo = res["righe_scartate"]
    
    righe_senza_codice = sum(1 for p in preview if not p.get("supplier_code"))
    # Un pack_qty pari a 1 (di default o non rilevato) significa senza confezionamento esplicito
    righe_senza_pack = sum(1 for p in preview if p.get("pack_qty") in (None, 1))
    righe_con_volume_peso = sum(1 for p in preview if p.get("volume_ml") is not None) # weight_g is always None for now
    
    auto_match = sum(1 for p in preview if p.get("decision") == "auto_match")
    parking_70_89 = sum(1 for p in preview if p.get("decision") == "parking" and p.get("score", 0) >= 70.0)
    parking_under_70 = sum(1 for p in preview if p.get("decision") == "parking" and p.get("score", 0) < 70.0)
    
    # Categorie
    categories = [p.get("category") for p in preview if p.get("category") is not None]
    cat_counts = dict(Counter(categories))
    
    # Ordinamento per score crescente
    sorted_by_score = sorted(preview, key=lambda x: x.get("score", 0))
    top_30_low_score = sorted_by_score[:30]
    
    # Warning
    warning_rows = [p for p in preview if p.get("warning")]
    sorted_warnings = sorted(warning_rows, key=lambda x: x.get("score", 0))
    top_30_warning = sorted_warnings[:30]
    
    # Casi peggiori (under 70 o con blocco o warning critico)
    casi_peggiori = sorted_by_score[:30]
    
    # Stampa i risultati
    print("============================================================")
    print("📊 REPORT QUALITÀ DRY RUN: storico_prezzi_navas.xlsx")
    print("============================================================")
    print(f"Righe Totali: {righe_totali}")
    print(f"Righe con prezzo valido: {righe_con_prezzo}")
    print(f"Righe senza prezzo (scartate): {righe_senza_prezzo}")
    print(f"Righe senza codice fornitore: {righe_senza_codice}")
    print(f"Righe senza pack_qty (o pack=1): {righe_senza_pack}")
    print(f"Righe con volume/peso riconosciuto: {righe_con_volume_peso}")
    print("------------------------------------------------------------")
    print(f"Auto-Match previsti: {auto_match}")
    print(f"Parking Area (70-89): {parking_70_89}")
    print(f"Parking Area (<70): {parking_under_70}")
    print(f"Errori parsing totali: {len(errori_parsing)}")
    print("------------------------------------------------------------")
    print("Conteggio Categorie Inferite:")
    for cat, count in cat_counts.items():
        print(f"  - {cat}: {count}")
    print("============================================================")
    
    # Scrivi il report in formato JSON per l'ispezione
    report_data = {
      "righe_totali": righe_totali,
      "righe_con_prezzo": righe_con_prezzo,
      "righe_senza_prezzo": righe_senza_prezzo,
      "righe_senza_codice": righe_senza_codice,
      "righe_senza_pack": righe_senza_pack,
      "righe_con_volume_peso": righe_con_volume_peso,
      "auto_match": auto_match,
      "parking_70_89": parking_70_89,
      "parking_under_70": parking_under_70,
      "cat_counts": cat_counts,
      "top_30_low_score": [{
          "row_index": p["row_index"],
          "raw_description": p["raw_description"],
          "score": p["score"],
          "warning": p["warning"],
          "decision": p["decision"]
      } for p in top_30_low_score],
      "top_30_warning": [{
          "row_index": p["row_index"],
          "raw_description": p["raw_description"],
          "score": p["score"],
          "warning": p["warning"]
      } for p in top_30_warning[:30]]
    }
    
    with open("data/import_samples/dry_run_report_navas.json", "w") as out:
        json.dump(report_data, out, cls=CustomEncoder, indent=2)
        
    print("Report salvato in data/import_samples/dry_run_report_navas.json")
    
    # Mostra i primi 3 casi peggiori per debug immediato
    print("\nTop 5 casi con score più basso:")
    for p in top_30_low_score[:5]:
        print(f"  Riga {p['row_index']} | {p['raw_description']} | Score: {p['score']} | Dec: {p['decision']} | Warn: {p['warning']}")

if __name__ == "__main__":
    asyncio.run(generate_report())
