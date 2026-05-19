import asyncio
import sys
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory, engine

async def main():
    async with async_session_factory() as session:
        # Find Navas supplier ID
        res_forn = await session.execute(text("SELECT id, nome_azienda FROM fornitori WHERE nome_azienda ILIKE '%Navas%'"))
        fornitore = res_forn.first()
        if not fornitore:
            print("❌ Fornitore 'Navas' non trovato nel database.")
            return
        fornitore_id = fornitore.id
        print(f"🌱 Trovato Fornitore: {fornitore.nome_azienda} (ID: {fornitore_id})")

        # Find Admin user ID
        res_admin = await session.execute(text("SELECT id FROM utenti WHERE ruolo = 'admin' LIMIT 1"))
        admin_id = res_admin.scalar()
        if not admin_id:
            admin_id = 1
        print(f"🌱 User ID Admin per Alias: {admin_id}")

        # Fetch all invoice rows to process
        res_rows = await session.execute(text("""
            SELECT id, codice_fornitore_raw, descrizione_fornitore_raw, prezzo_unitario_fatturato, unita_misura_fattura
            FROM righe_fattura
        """))
        all_rows = res_rows.all()
        print(f"🌱 Caricate {len(all_rows)} righe fattura dal database.")

        # Group by description to identify unique products
        product_groups = {}
        for row in all_rows:
            desc = row.descrizione_fornitore_raw
            if not desc:
                continue
            if desc not in product_groups:
                product_groups[desc] = {
                    "codes": set(),
                    "prices": [],
                    "uoms": set(),
                    "row_ids": []
                }
            if row.codice_fornitore_raw and row.codice_fornitore_raw != 'None':
                product_groups[desc]["codes"].add(row.codice_fornitore_raw)
            if row.unita_misura_fattura and row.unita_misura_fattura != 'None':
                product_groups[desc]["uoms"].add(row.unita_misura_fattura)
            product_groups[desc]["prices"].append(Decimal(str(row.prezzo_unitario_fatturato)))
            product_groups[desc]["row_ids"].append(row.id)

        print(f"🌱 Trovati {len(product_groups)} prodotti unici (per descrizione).")

        used_skus = set()
        created_listino_count = 0
        created_alias_count = 0
        updated_rows_count = 0

        # Process each product group
        for desc, info in product_groups.items():
            # Determine code
            code = list(info["codes"])[0] if info["codes"] else None
            # Determine price (minimum non-zero price, or just minimum)
            prices = [p for p in info["prices"] if p > 0]
            min_price = min(prices) if prices else min(info["prices"]) if info["prices"] else Decimal("0.0")
            # Determine UoM
            uom = list(info["uoms"])[0] if info["uoms"] else "Pz"

            # Generate SKU
            sku = None
            if code:
                # Clean code
                sku = re.sub(r'[^a-zA-Z0-9\-]+', '_', code).upper().strip('_')
            
            if not sku:
                # Clean description
                clean_desc = re.sub(r'[^a-zA-Z0-9\-]+', '_', desc).upper().strip('_')
                sku = f"SKU_{clean_desc[:40]}"

            # Ensure SKU uniqueness
            base_sku = sku
            counter = 1
            while sku in used_skus:
                sku = f"{base_sku[:45]}_{counter}"
                counter += 1
            used_skus.add(sku)

            # 1. Insert into listino_master
            # Note: postgres table 'listino_master' has fields: fornitore_id, sku_interno, descrizione, prezzo_pattuito, unita_misura, data_inizio_validita
            await session.execute(text("""
                INSERT INTO listino_master (fornitore_id, sku_interno, descrizione, prezzo_pattuito, unita_misura, data_inizio_validita)
                VALUES (:f_id, :sku, :desc, :prezzo, :uom, :start_date)
            """), {
                "f_id": fornitore_id,
                "sku": sku,
                "desc": desc,
                "prezzo": min_price,
                "uom": uom,
                "start_date": date(2025, 1, 1)
            })
            created_listino_count += 1

            # 2. Insert into alias_prodotti if there are codes
            # Note: 'alias_prodotti' has fields: fornitore_id, codice_fornitore_originale, sku_interno, coefficiente_conversione, confermato_da_user_id, created_at
            for c in info["codes"]:
                # Check if this alias already exists (should not, but safety check)
                res_alias_ex = await session.execute(text("""
                    SELECT id FROM alias_prodotti 
                    WHERE fornitore_id = :f_id AND codice_fornitore_originale = :code
                """), {"f_id": fornitore_id, "code": c})
                if not res_alias_ex.scalar():
                    await session.execute(text("""
                        INSERT INTO alias_prodotti (fornitore_id, codice_fornitore_originale, sku_interno, coefficiente_conversione, confermato_da_user_id, created_at)
                        VALUES (:f_id, :code, :sku, 1.0, :admin_id, :created_at)
                    """), {
                        "f_id": fornitore_id,
                        "code": c,
                        "sku": sku,
                        "admin_id": admin_id,
                        "created_at": datetime.now(timezone.utc)
                    })
                    created_alias_count += 1

            # 3. Update righe_fattura setting sku_interno and stato_matching='matched'
            row_ids = info["row_ids"]
            if row_ids:
                # Chunk list to avoid parameter limits in query if very large
                chunk_size = 500
                for i in range(0, len(row_ids), chunk_size):
                    chunk = row_ids[i:i+chunk_size]
                    await session.execute(text("""
                        UPDATE righe_fattura 
                        SET sku_interno = :sku, stato_matching = 'matched' 
                        WHERE id = ANY(:ids)
                    """), {"sku": sku, "ids": chunk})
                    updated_rows_count += len(chunk)

        # Commit transaction
        await session.commit()
        print("🎉 SUCCESS! Inizializzazione completata.")
        print(f" - Creati {created_listino_count} record in 'listino_master'")
        print(f" - Creati {created_alias_count} record in 'alias_prodotti'")
        print(f" - Aggiornate {updated_rows_count} righe in 'righe_fattura'")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
