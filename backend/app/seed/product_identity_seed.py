import asyncio
from datetime import date
from decimal import Decimal
from sqlalchemy import select, and_

from app.database import async_session_factory
from app.models.products import Product, SupplierProductAlias, ProductEquivalenceGroup, ProductEquivalenceGroupItem
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.services.normalization import normalize_text


async def seed_product_identity():
    """Popola il database con dati di test per il Product Identity Layer."""
    async with async_session_factory() as session:
        print("🌱 Seeding Product Identity Layer...")

        # ── 1. Crea o recupera i fornitori ──
        suppliers_data = [
            {"nome_azienda": "Eurocarta", "partita_iva": "11111111111", "email_contatto": "ordini@eurocarta.it"},
            {"nome_azienda": "Navas Srl", "partita_iva": "22222222222", "email_contatto": "commerciale@navas.it"},
            {"nome_azienda": "Altro Fornitore", "partita_iva": "33333333333", "email_contatto": "info@altro.it"},
        ]

        suppliers = {}
        for s in suppliers_data:
            stmt = select(Fornitore).where(Fornitore.partita_iva == s["partita_iva"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                existing = Fornitore(
                    partita_iva=s["partita_iva"],
                    nome_azienda=s["nome_azienda"],
                    attivo_whitelist=True,
                    email_contatto=s["email_contatto"]
                )
                session.add(existing)
                await session.flush()
                print(f"  Fornitore creato: {s['nome_azienda']}")
            suppliers[s["nome_azienda"]] = existing

        # ── 2. Crea i Prodotti Canonici ──
        products_data = [
            {
                "sku_interno": "BICCHIERE_CAFFE",
                "canonical_name": "Bicchiere caffè",
                "brand": None,
                "category": "monouso",
                "subcategory": "bicchiere",
                "volume_ml": 80,
                "comparison_unit": "piece",
                "unit_count": 1,
            },
            {
                "sku_interno": "BICCHIERE_ACQUA",
                "canonical_name": "Bicchiere acqua",
                "brand": None,
                "category": "monouso",
                "subcategory": "bicchiere",
                "volume_ml": 200,
                "comparison_unit": "piece",
                "unit_count": 1,
            },
            {
                "sku_interno": "BICCHIERE_COCKTAIL",
                "canonical_name": "Bicchiere cocktail",
                "brand": None,
                "category": "monouso",
                "subcategory": "bicchiere",
                "volume_ml": 300,
                "comparison_unit": "piece",
                "unit_count": 1,
            },
            {
                "sku_interno": "TOVAGLIOLO_40X40",
                "canonical_name": "Tovagliolo 40x40",
                "brand": None,
                "category": "monouso",
                "subcategory": "tovagliolo",
                "comparison_unit": "piece",
                "unit_count": 1,
            },
            {
                "sku_interno": "CANNUCCIA_NERA",
                "canonical_name": "Cannuccia nera",
                "brand": None,
                "category": "monouso",
                "subcategory": "cannuccia",
                "comparison_unit": "piece",
                "unit_count": 1,
            },
            {
                "sku_interno": "ACQUA_NATURALE_50CL_PET",
                "canonical_name": "Acqua naturale 50cl pet",
                "brand": None,
                "category": "acqua",
                "subcategory": "naturale",
                "volume_ml": 500,
                "comparison_unit": "liter",
                "container_type": "pet",
                "unit_count": 1,
            },
            {
                "sku_interno": "COCA_COLA_33CL_LATTINA",
                "canonical_name": "Coca Cola 33cl lattina",
                "brand": "coca cola",
                "category": "soft_drink",
                "subcategory": "cola",
                "volume_ml": 330,
                "comparison_unit": "liter",
                "container_type": "lattina",
                "unit_count": 1,
            },
        ]

        products = {}
        for p in products_data:
            stmt = select(Product).where(Product.sku_interno == p["sku_interno"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                existing = Product(
                    sku_interno=p["sku_interno"],
                    canonical_name=p["canonical_name"],
                    normalized_name=normalize_text(p["canonical_name"]),
                    brand=p.get("brand"),
                    category=p.get("category"),
                    subcategory=p.get("subcategory"),
                    volume_ml=p.get("volume_ml"),
                    weight_g=p.get("weight_g"),
                    unit_count=p.get("unit_count", 1),
                    container_type=p.get("container_type"),
                    comparison_unit=p.get("comparison_unit", "piece"),
                    is_active=True
                )
                session.add(existing)
                await session.flush()
                print(f"  Prodotto canonico creato: {p['sku_interno']}")
            products[p["sku_interno"]] = existing

        # ── 3. Crea gli Alias per i Fornitori ──
        aliases_data = [
            # Bicchiere Caffè
            {
                "supplier": "Eurocarta",
                "sku": "BICCHIERE_CAFFE",
                "supplier_code": "EC-BC-80",
                "raw_description": "BICCH. CAFFE 80CC X100",
                "pack_qty": 100,
                "volume_ml": 80,
                "price": Decimal("2.5000"),
            },
            {
                "supplier": "Navas Srl",
                "sku": "BICCHIERE_CAFFE",
                "supplier_code": "NV-BC-75",
                "raw_description": "BICCHIERE CAFFE BIANCO 75ML PZ100",
                "pack_qty": 100,
                "volume_ml": 75,
                "price": Decimal("2.8000"),
            },
            {
                "supplier": "Altro Fornitore",
                "sku": "BICCHIERE_CAFFE",
                "supplier_code": "AL-BC-50",
                "raw_description": "BICCHIERINO CAFFE MONOUSO PZ50",
                "pack_qty": 50,
                "price": Decimal("1.5500"),
            },
        ]

        for a in aliases_data:
            supplier = suppliers[a["supplier"]]
            product = products[a["sku"]]

            # Verifica se l'alias esiste
            stmt = select(SupplierProductAlias).where(
                and_(
                    SupplierProductAlias.supplier_id == supplier.id,
                    SupplierProductAlias.supplier_code == a["supplier_code"]
                )
            )
            existing_alias = (await session.execute(stmt)).scalar_one_or_none()
            if not existing_alias:
                new_alias = SupplierProductAlias(
                    supplier_id=supplier.id,
                    product_id=product.id,
                    supplier_code=a["supplier_code"],
                    raw_description=a["raw_description"],
                    normalized_description=normalize_text(a["raw_description"]),
                    pack_qty=a.get("pack_qty"),
                    volume_ml=a.get("volume_ml"),
                    status="approved",
                    source="manual",
                    confidence_score=1.0
                )
                session.add(new_alias)
                print(f"  Alias creato: {a['raw_description']} -> {a['sku']}")

            # Crea listino attivo
            stmt_listino = select(ListinoMaster).where(
                and_(
                    ListinoMaster.fornitore_id == supplier.id,
                    ListinoMaster.sku_interno == product.sku_interno,
                    ListinoMaster.data_scadenza.is_(None)
                )
            )
            existing_listino = (await session.execute(stmt_listino)).scalar_one_or_none()
            if not existing_listino:
                new_listino = ListinoMaster(
                    fornitore_id=supplier.id,
                    sku_interno=product.sku_interno,
                    descrizione=a["raw_description"],
                    prezzo_pattuito=a["price"],
                    unita_misura="Pz",
                    data_inizio_validita=date(2025, 1, 1),
                    data_scadenza=None
                )
                session.add(new_listino)
                print(f"  Listino creato: {supplier.nome_azienda} - {product.sku_interno} @ € {a['price']}")

        await session.commit()
        print("🎉 Seeding completato con successo!")


if __name__ == "__main__":
    asyncio.run(seed_product_identity())
