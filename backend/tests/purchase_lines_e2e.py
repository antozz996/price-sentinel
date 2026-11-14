"""Base comune delle righe d'acquisto su PostgreSQL usa e getta.

Esegue davvero le espressioni SQL di services/purchase_lines.py (mappa unità,
segno TD04/TD08, NOT EXISTS sulle esclusioni, tenant, tabella VALUES delle
conversioni) e verifica che diano gli stessi numeri degli helper Python.
Solo tramite run_ci_disposable_e2e.py o un altro database usa e getta; dati sintetici.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import psycopg2
from sqlalchemy import func, select

import app.main  # noqa: F401  (registers every model)
from app.database import async_session_factory
from app.models.esclusi import RigaEsclusaStatistiche, SKUEscluso
from app.models.fatture import Fattura, RigaFattura, StatoMatching, TipoDocumento, XMLRaw
from app.models.products import Product, SupplierProductAlias
from app.services import purchase_lines as pl
from app.services.normalization import normalize_text

DSN = os.environ["TEST_DATABASE_DSN"]
TENANT_1 = SimpleNamespace(id=1, tenant_id=1)
TENANT_2 = SimpleNamespace(id=2, tenant_id=2)
UNITS = ["N.", "NR", "K.", "KGM", "", None, "Lt", "CF", "PZ.", "COL", " ct "]


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def seed_masters() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id, nome_struttura, piva_riferimento, tipologia)
                values (1, 'Struttura Sintetica CI', '00000000001', 'ristorante');
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (9,'10000000009','Fornitore Sintetico Panini',true),
                       (22,'10000000022','Fornitore Sintetico Gin',true);
            """)


class Seed:
    def __init__(self, db) -> None:
        self.db = db
        self.n = 0
        self.invoices = 0

    async def invoice(self, fornitore: int, tipo: TipoDocumento, tenant: int | None = 1) -> Fattura:
        self.invoices += 1
        xml = XMLRaw(payload="<synthetic/>", hash_idempotenza=f"ci-pl-{self.invoices}",
                     data_ricezione=datetime.now(timezone.utc))
        self.db.add(xml)
        await self.db.flush()
        invoice = Fattura(
            xml_raw_id=xml.id, fornitore_id=fornitore, location_id=1, numero_documento=f"CI-PL-{self.invoices}",
            data_documento=date(2026, 5, self.invoices), data_ricezione_sdi=date(2026, 5, self.invoices),
            tipo_documento=tipo, totale_imponibile=Decimal("0"), tenant_id=tenant,
        )
        self.db.add(invoice)
        await self.db.flush()
        return invoice

    async def line(self, invoice: Fattura, sku: str | None, code: str | None, description: str, uom: str | None,
                   qty: str, price: str, discount: str = "0", omaggio: bool = False) -> RigaFattura:
        self.n += 1
        line = RigaFattura(
            fattura_id=invoice.id, numero_linea=self.n, codice_fornitore_raw=code,
            descrizione_fornitore_raw=description, sku_interno=sku,
            prezzo_unitario_fatturato=Decimal(price), sconto_percentuale=Decimal(discount),
            # Deliberately wrong: the shared base must never read this column.
            prezzo_netto_normalizzato=Decimal("0.0001"),
            quantita=Decimal(qty), unita_misura_fattura=uom, is_omaggio=omaggio,
            stato_matching=StatoMatching.matched,
        )
        self.db.add(line)
        await self.db.flush()
        return line


async def seed() -> dict:
    async with async_session_factory() as db:
        s = Seed(db)
        panino = Product(sku_interno="CI-PANINO", canonical_name="MINI PANINO", comparison_unit="Pz",
                         unit_count=1, is_active=True)
        gin = Product(sku_interno="CI-GIN", canonical_name="GIN 100 CL", comparison_unit="Pz",
                      unit_count=1, is_active=True)
        escluso = Product(sku_interno="CI-ESCLUSO", canonical_name="ESCLUSO", comparison_unit="Pz",
                          unit_count=1, is_active=True)
        db.add_all([panino, gin, escluso])
        await db.flush()
        desc = "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO"
        db.add(SupplierProductAlias(supplier_id=9, product_id=panino.id, supplier_code="PPANVE",
                                    raw_description=desc, normalized_description=normalize_text(desc),
                                    pack_qty=100, source="manual", status="approved"))
        db.add(SKUEscluso(sku_interno="CI-ESCLUSO"))

        acquisto = await s.invoice(9, TipoDocumento.TD01)
        await s.line(acquisto, "CI-PANINO", "PPANVE", desc, "CT", "2", "26.8926", "0.01")
        await s.line(acquisto, "CI-PANINO", "PPANVE", desc, "CT", "1", "0", omaggio=True)
        # Description with quote and backslash: the VALUES join must still match it.
        await s.line(acquisto, "CI-PANINO", None, "PANINO d'oro \\ senza codice", "CT", "1", "20")
        await s.line(acquisto, "CI-ESCLUSO", "X1", "ESCLUSO", "PZ", "50", "1")
        riga_esclusa = await s.line(acquisto, "CI-PANINO", "PPANVE", desc, "CT", "10", "99")
        await s.line(acquisto, None, None, "TRASPORTO", None, "1", "15")
        for i, uom in enumerate(UNITS):
            await s.line(acquisto, None, None, f"UNITA {i}", uom, "0", "0")
        db.add(RigaEsclusaStatistiche(riga_fattura_id=riga_esclusa.id, motivo="prezzo anomalo"))

        gin_buy = await s.invoice(22, TipoDocumento.TD01)
        await s.line(gin_buy, "CI-GIN", "GIN0001", "GIN 100 CL", "BT", "6", "15.1633")
        await s.line(gin_buy, "CI-GIN", "GIN0001", "GIN 100 CL", "BT", "12", "13.3033")
        reso = await s.invoice(22, TipoDocumento.TD04)
        await s.line(reso, "CI-GIN", "GIN0001", "GIN 100 CL", "BT", "374", "15.1639")
        nc_semplificata = await s.invoice(22, TipoDocumento.TD08, tenant=None)  # legacy: tenant 1
        await s.line(nc_semplificata, "CI-GIN", "GIN0001", "GIN 100 CL", "BT", "1", "15.16")

        altro_tenant = await s.invoice(22, TipoDocumento.TD01, tenant=2)
        await s.line(altro_tenant, "CI-GIN", "GIN0001", "GIN 100 CL", "BT", "1000", "1")
        await db.commit()
        return {"panino": panino.id}


async def aggregate(db, user):
    base = pl.purchase_lines_select(user, require_sku=True).subquery("pl")
    conversions = await pl.load_conversions(db, base)
    conv = pl.conversion_table(conversions)
    stmt = (
        select(
            base.c.sku_interno,
            func.sum(base.c.quantita_firmata).label("quantita"),
            func.sum(base.c.importo_netto).label("spesa"),
            func.sum(pl.converted_quantity_sql(base, conv)).label("quantita_confronto"),
            func.min(pl.converted_unit_price_sql(base, conv)).filter(base.c.in_media).label("minimo"),
            func.count().label("righe"),
        )
        .select_from(base.outerjoin(conv, pl.conversion_join(base, conv)))
        .group_by(base.c.sku_interno)
    )
    return {r.sku_interno: r for r in (await db.execute(stmt)).all()}, conversions


async def run() -> None:
    await seed()
    async with async_session_factory() as db:
        rows, conversions = await aggregate(db, TENANT_1)
        check("excluded SKU is not in the aggregate", "CI-ESCLUSO" not in rows)
        gin = rows["CI-GIN"]
        check("TD04 and TD08 are subtracted (-357 BT)", gin.quantita == Decimal("-357"))
        check("credit notes give negative spend (-5435.84)", round(gin.spesa, 2) == Decimal("-5435.84"))
        check("other tenant invoice is not counted", gin.righe == 4)
        panino = rows["CI-PANINO"]
        check("excluded line (righe_escluse_statistiche) is not counted", panino.righe == 3)
        check("free carton keeps its 100 pieces", panino.quantita_confronto is not None
              and panino.quantita_confronto == Decimal("300"))
        check("spend uses invoiced price x (1 - discount), not prezzo_netto_normalizzato",
              round(panino.spesa, 2) == Decimal("73.78"))
        check("minimum per piece ignores the free carton", round(panino.minimo, 4) == Decimal("0.2689"))
        no_code = [c for k, c in conversions.items() if k.codice_fornitore is None and k.product_id is not None]
        check("line without code and without known pack is not reliable", no_code and not no_code[0].reliable)

        other_rows, _ = await aggregate(db, TENANT_2)
        check("tenant 2 sees only its invoice", other_rows["CI-GIN"].quantita == Decimal("1000"))

        units = (await db.execute(
            select(RigaFattura.unita_misura_fattura, pl.normalized_unit_sql(RigaFattura.unita_misura_fattura))
            .where(RigaFattura.descrizione_fornitore_raw.like("UNITA %"))
        )).all()
        check("SQL unit map equals the Python one",
              all(sql_unit == pl.normalized_unit(raw) for raw, sql_unit in units) and len(units) == len(UNITS))
        empty = pl.conversion_table({})
        check("empty conversion table runs", (await db.execute(select(func.count()).select_from(empty))).scalar() == 1)


if __name__ == "__main__":
    seed_masters()
    asyncio.run(run())
    print("PASS: purchase lines E2E", flush=True)
