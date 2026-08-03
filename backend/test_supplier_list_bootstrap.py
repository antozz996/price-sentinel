"""Regression test for controlled first-list import and explicit price units."""

import asyncio
from decimal import Decimal
from io import BytesIO

import openpyxl
from sqlalchemy import delete, func, select

import app.models  # noqa: F401 - registra tutte le tabelle nel metadata
from app.database import Base, async_session_factory, engine
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import MatchCandidate, Product, SupplierProductAlias
from app.services.matching import normalize_price_for_comparison
from app.services.supplier_list_import import import_supplier_list_excel, normalize_price_uom


RAW_DESCRIPTION = "FEVER-TREE ELDERFLOWER TONIC WATER 200 ML"


def build_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Prodotto", "Unità di Misura", "Prezzo netto", "Confezione"])
    sheet.append([RAW_DESCRIPTION, "bottiglia", "0,83 €", 24])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


async def scalar_count(db, model) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def run() -> None:
    file_bytes = build_workbook()
    assert normalize_price_uom("CT") == "box"
    assert normalize_price_uom("CS") == "box"
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_session_factory() as db:
        existing_supplier_id = (
            await db.execute(
                select(Fornitore.id).where(Fornitore.partita_iva == "99999999991")
            )
        ).scalar_one_or_none()
        if existing_supplier_id is not None:
            await db.execute(delete(ListinoMaster).where(ListinoMaster.fornitore_id == existing_supplier_id))
            await db.execute(delete(MatchCandidate).where(MatchCandidate.supplier_id == existing_supplier_id))
            await db.execute(delete(SupplierProductAlias).where(SupplierProductAlias.supplier_id == existing_supplier_id))
            await db.execute(delete(Fornitore).where(Fornitore.id == existing_supplier_id))
        await db.execute(delete(Product).where(Product.canonical_name == RAW_DESCRIPTION))
        await db.commit()
        supplier = Fornitore(
            partita_iva="99999999991",
            nome_azienda="Bootstrap Test Supplier",
            attivo_whitelist=True,
        )
        db.add(supplier)
        await db.commit()

        before = {
            "products": await scalar_count(db, Product),
            "aliases": await scalar_count(db, SupplierProductAlias),
            "prices": await scalar_count(db, ListinoMaster),
            "candidates": await scalar_count(db, MatchCandidate),
        }

        dry = await import_supplier_list_excel(
            db,
            supplier.id,
            file_bytes,
            dry_run=True,
            create_missing_products=True,
        )
        assert dry["dry_run"] is True
        assert dry["righe_importate"] == 1
        assert dry["prodotti_creati"] == 1
        assert dry["match_candidates_creati"] == 0
        assert dry["preview"][0]["decision"] == "new_product"
        assert dry["preview"][0]["uom"] == "bottle"
        assert dry["preview"][0]["pack_qty"] == 24
        assert before == {
            "products": await scalar_count(db, Product),
            "aliases": await scalar_count(db, SupplierProductAlias),
            "prices": await scalar_count(db, ListinoMaster),
            "candidates": await scalar_count(db, MatchCandidate),
        }, "Il dry run ha scritto nel database"

        real = await import_supplier_list_excel(
            db,
            supplier.id,
            file_bytes,
            dry_run=False,
            create_missing_products=True,
        )
        await db.commit()
        assert real["righe_importate"] == 1
        assert real["prodotti_creati"] == 1
        assert real["match_candidates_creati"] == 0

        product = (
            await db.execute(select(Product).where(Product.canonical_name == RAW_DESCRIPTION))
        ).scalar_one()
        alias = (
            await db.execute(
                select(SupplierProductAlias).where(
                    SupplierProductAlias.supplier_id == supplier.id,
                    SupplierProductAlias.product_id == product.id,
                )
            )
        ).scalar_one()
        price = (
            await db.execute(
                select(ListinoMaster).where(
                    ListinoMaster.fornitore_id == supplier.id,
                    ListinoMaster.supplier_product_alias_id == alias.id,
                    ListinoMaster.data_scadenza.is_(None),
                )
            )
        ).scalar_one()

        assert product.comparison_unit == "bottle"
        assert product.unit_count == 1
        assert alias.pack_qty == 24
        assert alias.source == "supplier_list_bootstrap"
        assert price.prezzo_pattuito == Decimal("0.83")
        assert price.unita_misura == "bottle"

        second = await import_supplier_list_excel(
            db,
            supplier.id,
            file_bytes,
            dry_run=False,
            create_missing_products=True,
        )
        await db.commit()
        assert second["prodotti_creati"] == 0
        assert second["alias_gia_esistenti_riconosciuti"] == 1
        assert second["prezzi_invariati"] == 1
        assert await scalar_count(db, Product) == before["products"] + 1
        assert await scalar_count(db, SupplierProductAlias) == before["aliases"] + 1
        assert await scalar_count(db, ListinoMaster) == before["prices"] + 1

        per_bottle = normalize_price_for_comparison(
            Decimal("0.83"), Decimal("1"), "bottiglia", product, alias,
            target_comparison_unit="bottle",
        )
        assert per_bottle.reliable and per_bottle.normalized_unit_price == Decimal("0.83")

        per_case = normalize_price_for_comparison(
            Decimal("19.92"), Decimal("1"), "cassa", product, alias,
            target_comparison_unit="bottle",
        )
        assert per_case.reliable and per_case.normalized_unit_price == Decimal("0.83")

        ambiguous = normalize_price_for_comparison(
            Decimal("19.92"), Decimal("1"), "", product, alias,
            target_comparison_unit="bottle",
        )
        assert not ambiguous.reliable
        assert ambiguous.normalized_unit_price == Decimal("19.92")

    print("PASS: controlled bootstrap, dry-run isolation, idempotence and explicit UOM (14/14)")


if __name__ == "__main__":
    asyncio.run(run())
