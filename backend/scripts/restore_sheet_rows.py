"""Explicit V2-only, transactional reconciliation of original workbook rows.

Defaults to rollback. Run with --apply only after checking the printed plan.
Never connects to V1; requires the exact expected database name.
"""
import argparse
import asyncio
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, text
from app.database import async_session_factory, engine
from app.models.products import Product
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore
from app.services.normalized_price_workbook import parse_normalized_price_workbook, _parse_price, _normalize


async def run(args):
    expected = args.database
    if expected != 'price_sentinel_v2_staging' and not expected.startswith('ps_v2_rowcheck_'):
        raise ValueError('Only V2 staging or disposable rowcheck databases are permitted')
    report = parse_normalized_price_workbook(Path(args.workbook).read_bytes())
    mapping = json.loads(Path(args.supplier_mapping).read_text())
    async with async_session_factory() as db:
        actual = await db.scalar(text('select current_database()'))
        if actual != expected:
            raise ValueError(f'Database mismatch: {actual}')
        await db.execute(text('select pg_advisory_xact_lock(481991, 2014)'))
        suppliers = {s.id: s for s in (await db.scalars(select(Fornitore).options())).all()}
        groups = {}
        pairs = set()
        for row in report['candidates']:
            key = row['source_product_key']
            supplier_id = mapping[row['supplier']]
            if supplier_id not in suppliers:
                raise ValueError('Supplier not found')
            price, state = _parse_price(row['quoted_value'])
            if state != 'valid':
                raise ValueError(f'Invalid original price at {row["source_cell"]}')
            pair = (key, supplier_id)
            if pair in pairs:
                raise ValueError(f'Repeated source row/supplier: {pair}')
            pairs.add(pair)
            group = groups.setdefault(key, [])
            if group and group[0]['product'] != row['product']:
                raise ValueError('Source identity has conflicting product names')
            group.append(row)
        existing = {p.sku_interno: p for p in (await db.scalars(select(Product))).all()}
        created = prices = incomplete = 0
        for key, rows in groups.items():
            sku = 'SG3-' + hashlib.sha256(key.encode()).hexdigest()[:16].upper()
            first = rows[0]
            product = existing.get(sku)
            if product:
                if product.canonical_name != first['product']:
                    raise ValueError('Existing row SKU has another name')
                continue
            units = {r['supplier_price_unit'] for r in rows if r.get('numeric_price') and r.get('supplier_price_unit')}
            product = Product(sku_interno=sku, canonical_name=first['product'],
                normalized_name=_normalize(first['product']), category=first['sector'],
                subcategory=first.get('subcategory'), comparison_unit=next(iter(units)) if len(units)==1 else None,
                is_active=True, is_commodity=False, unit_count=1)
            db.add(product)
            created += 1
            for row in rows:
                amount, _ = _parse_price(row['quoted_value'])
                unit = row.get('supplier_price_unit') if row.get('numeric_price') else None
                if not unit:
                    incomplete += 1
                description = row['product'] + '\nOrigine: ' + str(row.get('cell_note') or row['source_cell'])
                if row.get('packaging_note'):
                    description += '\n' + row['packaging_note']
                if not unit:
                    description += '\nDA COMPLETARE: prezzo originale, unità/confezione non confermata; non normalizzato.'
                db.add(ListinoMaster(fornitore_id=mapping[row['supplier']], sku_interno=sku,
                    descrizione=description, prezzo_pattuito=Decimal(amount), unita_misura=unit,
                    data_inizio_validita=date.today(), data_scadenza=None))
                prices += 1
        # Archive only the superseded V2 import; historical records are preserved.
        archived = 0
        for sku, product in existing.items():
            if sku and sku.startswith('SG2-') and product.is_active:
                product.is_active = False
                archived += 1
        await db.flush()
        summary = dict(products=len(groups), quotes=len(pairs), created=created,
            prices_created=prices, incomplete_prices=incomplete, archived=archived, apply=args.apply)
        print(json.dumps(summary))
        if args.apply:
            await db.commit()
        else:
            await db.rollback()
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--supplier-mapping', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args()))
