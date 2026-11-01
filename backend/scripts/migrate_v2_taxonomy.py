"""Normalize V2 categories safely. Dry-run by default; pass --apply to commit."""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session_factory, engine
from app.models.categories import MasterCategory, MasterSubcategory
from app.models.products import Product
from app.models.purchase_policy import SupplierCategoryCapability, SupplierSubcategoryCapability

TARGETS = {
    "Food": ("Prodotti alimentari", "#16a34a"),
    "Beverage": ("Bevande", "#0ea5e9"),
    "Materiali": ("Materiali, monouso e attrezzature", "#64748b"),
    "Giocattoli": ("Giocattoli", "#8b5cf6"),
    "Snack": ("Snack", "#f59e0b"),
}

def key(value):
    return value.strip().casefold() if value else ""

CATEGORY_GROUPS = {
    "Food": ["food", "ortofrutta", "alimentari & dispensa", "carni & salumi", "ittico & pesce", "latticini & formaggi", "ortofrutta fresca", "surgelati & congelati"],
    "Beverage": ["beverage", "acqua minerale", "alcolici & superalcolici", "beverage & soft drinks", "birre", "caffetteria & bar", "vini, spumanti & champagne"],
    "Materiali": ["materiali", "attrezzature & accessori", "detergenza & igiene", "monouso & tovagliato", "packaging & asporto"],
    "Giocattoli": ["giocattoli"],
    "Snack": ["snack"],
}
CATEGORY_MAP = {key(alias): target for target, aliases in CATEGORY_GROUPS.items() for alias in aliases}
SUBCATEGORY_MAP = {
    "pesce": "Pesce", "ittico & pesce": "Pesce",
    "carne": "Carne", "carni & hamburger": "Carne", "carni & salumi": "Carne", "salumi & affettati": "Carne",
    "frutta": "Frutta", "ortofrutta": "Frutta", "ortofrutta fresca": "Frutta",
}

async def main(apply_changes: bool):
    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        async with db.begin():
            products = (await db.scalars(select(Product))).all()
            cap_rows = (await db.scalars(select(SupplierCategoryCapability))).all()
            subcap_rows = (await db.scalars(select(SupplierSubcategoryCapability))).all()
            master_rows = (await db.scalars(select(MasterCategory))).all()
            sub_rows = (await db.scalars(select(MasterSubcategory))).all()

            unknown_products = sorted({p.category for p in products if key(p.category) and key(p.category) not in CATEGORY_MAP})
            unknown_caps = sorted({c.category for c in cap_rows if key(c.category) and key(c.category) not in CATEGORY_MAP})
            if unknown_products or unknown_caps:
                raise RuntimeError(f"Categorie non mappate; nessuna modifica applicata. Prodotti={unknown_products}; abilitazioni={unknown_caps}")

            product_changes = defaultdict(int)
            subcategory_clears = 0
            for p in products:
                target = CATEGORY_MAP.get(key(p.category))
                if target and p.category != target:
                    product_changes[f"{p.category} → {target}"] += 1
                mapped_sub = SUBCATEGORY_MAP.get(key(p.subcategory))
                if p.subcategory and (target != "Food" or not mapped_sub):
                    subcategory_clears += 1

            capability_groups = defaultdict(list)
            for row in cap_rows:
                target = CATEGORY_MAP.get(key(row.category))
                if target:
                    capability_groups[(row.supplier_id, target)].append(row)
            subcap_groups = defaultdict(list)
            subcaps_to_drop = 0
            for row in subcap_rows:
                target_cat = CATEGORY_MAP.get(key(row.categoria_nome))
                target_sub = SUBCATEGORY_MAP.get(key(row.subcategory))
                if target_cat == "Food" and target_sub:
                    subcap_groups[(row.supplier_id, target_cat, target_sub)].append(row)
                else:
                    subcaps_to_drop += 1

            print("ANTEPRIMA TAXONOMIA V2" if not apply_changes else "APPLICAZIONE MIGRAZIONE TAXONOMIA V2")
            print("Prodotti attivi per categoria:")
            active_counts = defaultdict(int)
            for p in products:
                if p.is_active and p.category:
                    active_counts[p.category] += 1
            for name, count in sorted(active_counts.items()):
                print(f"  {name}: {count}")
            print("Riclassificazioni prodotto:")
            for label, count in sorted(product_changes.items()):
                print(f"  {label}: {count}")
            print(f"Sottocategorie prodotto non ammesse che verranno svuotate: {subcategory_clears}")
            print(f"Abilitazioni settore: {len(cap_rows)} righe sorgenti → {len(capability_groups)} combinazioni fornitore/settore")
            print(f"Abilitazioni sottocategoria: {len(subcap_rows)} righe; da rimuovere perché fuori dalle 3 Food: {subcaps_to_drop}")
            print(f"Categorie master: {len(master_rows)} → {len(TARGETS)}")
            print(f"Sottocategorie master: {len(sub_rows)} → 3")
            print("Destinazioni: Food (Pesce, Carne, Frutta), Beverage, Materiali, Giocattoli, Snack")
            if not apply_changes:
                print("DRY-RUN: nessuna modifica eseguita. Per applicare: aggiungere --apply")
                return

            for p in products:
                target = CATEGORY_MAP.get(key(p.category))
                if target:
                    p.category = target
                if p.subcategory:
                    mapped_sub = SUBCATEGORY_MAP.get(key(p.subcategory))
                    p.subcategory = mapped_sub if target == "Food" and mapped_sub else None

            await db.execute(SupplierCategoryCapability.__table__.delete())
            for (supplier_id, target), rows in capability_groups.items():
                latest = max(rows, key=lambda r: r.updated_at)
                reasons = sorted({r.reason.strip() for r in rows if r.reason and r.reason.strip()})
                db.add(SupplierCategoryCapability(
                    supplier_id=supplier_id,
                    category=target,
                    enabled=any(r.enabled for r in rows),
                    reason="; ".join(reasons)[:2000] or None,
                    created_by=rows[0].created_by,
                    updated_by=latest.updated_by,
                    created_at=min(r.created_at for r in rows),
                    updated_at=now,
                ))

            await db.execute(SupplierSubcategoryCapability.__table__.delete())
            for (supplier_id, target_cat, target_sub), rows in subcap_groups.items():
                latest = max(rows, key=lambda r: r.updated_at)
                db.add(SupplierSubcategoryCapability(
                    supplier_id=supplier_id,
                    categoria_nome=target_cat,
                    subcategory=target_sub,
                    enabled=any(r.enabled for r in rows),
                    created_at=min(r.created_at for r in rows),
                    updated_at=now,
                ))

            await db.execute(MasterSubcategory.__table__.delete())
            for sub_name in ("Pesce", "Carne", "Frutta"):
                db.add(MasterSubcategory(categoria_nome="Food", nome=sub_name, is_active=True, created_at=now, updated_at=now))
            await db.execute(MasterCategory.__table__.delete())
            for name, (description, color) in TARGETS.items():
                db.add(MasterCategory(nome=name, descrizione=description, colore=color, is_active=True, created_at=now, updated_at=now))
            await db.flush()
        if apply_changes:
            print("Migrazione completata e committata.")
    await engine.dispose()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="applica e committa la migrazione; senza questo flag esegue solo anteprima")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
