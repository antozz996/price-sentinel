"""Fatture (elenco e dettaglio), Accordi commerciali ed estrazione listino da fatture.

Casi reali del rapporto schermate del 14/11/2026 (gruppo SPESA, export di
produzione): MINI PANINO EDNA Melius 2 CT a 26,89, Calypso VE.MO. fattura 6816,
nota di credito Navas n.146, THOMAS HENRY Navas BT + CT da 24, SACCHI KITO in
CT/CNF/PZ. Nessun database: le query vengono compilate per PostgreSQL e i
risultati sono preparati a mano.
"""
import asyncio
import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import Response  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import accordi  # noqa: E402
from app.api.v1.fatture import list_fatture, list_righe_fattura, scaglione_percentage  # noqa: E402
from app.api.v1.listino import extract_invoice_price_items, group_invoice_price_lines  # noqa: E402
from app.models.fatture import TipoDocumento  # noqa: E402
from app.models.listino import PFATipo  # noqa: E402
from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.models.utenti import RuoloUtente  # noqa: E402
from app.services import purchase_lines as pl  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402

ADMIN = SimpleNamespace(id=1, ruolo=RuoloUtente.admin, location_id=None, tenant_id=1)


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class RecordingDb:
    """Records every statement and returns the scripted results in order."""

    def __init__(self, *results, get_result=None):
        self.results = list(results)
        self.statements = []
        self.get_result = get_result

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.results:
            raise AssertionError(f"unexpected query: {statement}")
        return _Result(self.results.pop(0))

    async def scalars(self, statement):
        return (await self.execute(statement)).scalars()

    async def get(self, _model, _pk, options=None):
        return self.get_result


def product(pid, sku, unit, name, unit_count=1):
    return Product(id=pid, sku_interno=sku, canonical_name=name, comparison_unit=unit, unit_count=unit_count)


def alias(aid, supplier, pid, code, description, pack=None, volume_ml=None, weight_g=None):
    return SupplierProductAlias(
        id=aid, supplier_id=supplier, product_id=pid, supplier_code=code, raw_description=description,
        normalized_description=normalize_text(description), pack_qty=pack, volume_ml=volume_ml,
        weight_g=weight_g, status="approved", source="manual",
    )


# ── Dati reali (export 14/11/2026) ──
MINI_PANINO = product(1, "SG3-52506F3CBE1143E1", "Pz", "MINI PANINO EDNA BURGHER")
MINI_PANINO_DESC = "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO"
MINI_PANINO_ALIAS = alias(2558, 9, 1, "PPANVE", MINI_PANINO_DESC, pack=100)

CALYPSO = product(645, "CAN-21-31-1793543247", "Pz", "Calypso calice fluttino bicchiere 113ml 54 pezzi")
CALYPSO_DESC = "Calypso calice fluttino bicchiere 113ml"
CALYPSO_ALIASES = [
    alias(2000, 21, 645, "BORBF54", CALYPSO_DESC + " 54 pezzi 128140203521990", pack=54, volume_ml=113),
    alias(2245, 21, 645, "BORCF", CALYPSO_DESC + " 128140VNA021990", pack=54, volume_ml=113),
]

THOMAS = product(798, "CAN-22-964-1793794633", "Pz", "THOMAS HENRY GINGER BEER 200 ML")
THOMAS_ALIAS = alias(2338, 22, 798, "GINGER5", "THOMAS HENRY GINGER BEER 200 ML", pack=24, volume_ml=200)

SACCHI = product(575, "SG3-46971BE66F6C2332", "CT", "SACCHI X RAC. RIFIUTI MIS, 130X150 COL. AMBRA")
SACCHI_DESC = "SACCHI X RAC. RIFIUTI MIS, 130X150 COL. AMBRA"
SACCHI_ALIASES = [
    alias(2672, 24, 575, None, SACCHI_DESC),
    alias(4655, 24, 575, None, "SACCHI X RAC. RIFIUTI MIS. 130x150 COL. AMBRA"),
]

# 66 righe MELIUS PPANVE (quantità CT, prezzo unitario, sconto %), dalla più recente.
PANINO_EDNA_ROWS = [
    ("2", "26.89", "0"), ("1", "26.8", "0"), ("1", "26.8", "0"), ("1", "26.8", "0"), ("1", "26.8926", "0.01"),
    ("1", "26.8926", "0.01"), ("1", "26.89", "0"), ("1", "26.89", "0"), ("1", "26.6", "0"), ("1", "26.6", "0"),
    ("1", "26.9826", "0.01"), ("1", "25.9", "0"), ("1", "26.65", "0"), ("1", "26.6", "0"), ("1", "26.6", "0"),
    ("1", "26.89", "0"), ("1", "26.9", "0"), ("1", "25.9824", "0.0092"), ("2", "26.6398", "0"),
    ("1", "25.9824", "0.0092"), ("3", "26.5", "0"), ("4", "26.6398", "0"), ("1", "26.5", "0"), ("3", "26.98", "0"),
    ("2", "26.0344", "0"), ("2", "26.2362", "0.0046"), ("2", "26.298", "0"), ("2", "26.826", "0.0037"),
    ("4", "26.986", "0.0037"), ("3", "26.998", "0.0049"), ("3", "26.986", "0"), ("2", "26.0344", "0"),
    ("2", "26.986", "0.0037"), ("2", "26.98", "0"), ("3", "26.98", "0"), ("3", "26.5", "0"), ("40", "26.5", "0"),
    ("2", "26.0344", "0"), ("2", "26.98", "0"), ("2", "26.986", "0.0037"), ("2", "26.986", "0.0037"),
    ("4", "26.986", "0.0037"), ("3", "26.5", "0"), ("3", "26.5", "0"), ("2", "26.98", "0"), ("1", "26.2361", "0"),
    ("1", "26.2361", "0"), ("2", "26.365", "0"), ("4", "26.36", "0"), ("3", "26.36", "0"), ("2", "26.36", "0"),
    ("3", "26.9", "0"), ("1", "26.986", "0"), ("2", "26.9826", "0"), ("2", "26.9826", "0"), ("3", "26.98", "0"),
    ("6", "26.9826", "0"), ("2", "26.9826", "0"), ("2", "26.5", "0"), ("2", "26.526", "0.0038"), ("2", "26.89", "0"),
    ("3", "26.8926", "0"), ("2", "26.9", "0"), ("2", "26.9", "0"), ("2", "26.6", "0"), ("1", "26.6", "0"),
]

# 28 righe KITO dello SKU SACCHI 130X150 (data, quantità, unità, prezzo).
SACCHI_KITO_ROWS = [
    ("2026-10-09", "2", "CT", "23"), ("2026-01-22", "2", "CT", "22.5"), ("2026-03-05", "2", "CT", "22.5"),
    ("2026-02-12", "2", "CT", "22.5"), ("2026-03-26", "3", "CT", "22.5"), ("2026-04-10", "4", "CNF", "22.5"),
    ("2026-04-23", "1", "CNF", "22.5"), ("2026-04-29", "5", "CT", "22.5"), ("2026-06-01", "4", "CT", "22.5"),
    ("2026-06-03", "3", "PZ", "23.5"), ("2026-06-30", "5", "CT", "23.5"), ("2026-06-11", "6", "CNF", "23.5"),
    ("2026-06-16", "3", "CT", "23.5"), ("2026-07-13", "2", "CT", "23"), ("2026-07-07", "4", "CT", "23"),
    ("2026-06-25", "4", "CT", "23.5"), ("2026-08-11", "2", "CT", "23"), ("2026-07-20", "2", "CT", "23"),
    ("2026-08-18", "3", "CNF", "23"), ("2026-07-27", "5", "CNF", "23"), ("2026-08-03", "3", "CT", "23"),
    ("2026-08-31", "3", "CNF", "23"), ("2026-09-07", "3", "CT", "23"), ("2026-10-01", "2", "CT", "23"),
    ("2026-09-22", "3", "CT", "23"), ("2026-02-12", "2", "CT", "23.625"), ("2026-06-25", "1", "CT", "24.5"),
    ("2026-07-20", "1", "CT", "24.5"),
]


def purchase_row(*, fornitore, product_obj, code, description, unit, qty, price, discount="0",
                 day=date(2026, 6, 1), tipo=TipoDocumento.TD01, location=1):
    """Una riga come la restituisce purchase_lines_select."""
    sign = pl.document_sign(tipo)
    net = pl.line_net_unit_price(price, discount)
    return SimpleNamespace(
        fornitore_id=fornitore, product_id=getattr(product_obj, "id", None),
        sku_interno=getattr(product_obj, "sku_interno", None), codice_fornitore=code, descrizione=description,
        unita_misura=unit, unita=pl.normalized_unit(unit), quantita=Decimal(qty), netto_unitario=net,
        quantita_firmata=sign * Decimal(qty), importo_netto=sign * net * Decimal(qty),
        data_documento=day, location_id=location, tipo_documento=tipo,
    )


def invoice_line(line_id, qty, unit, price, discount="0", pnn="0", sku=None, code=None, description=None):
    return SimpleNamespace(
        id=line_id, quantita=Decimal(qty), unita_misura_fattura=unit, prezzo_unitario_fatturato=Decimal(price),
        sconto_percentuale=Decimal(discount), prezzo_netto_normalizzato=Decimal(pnn), sku_interno=sku,
        codice_fornitore_raw=code, descrizione_fornitore_raw=description,
    )


def invoice(fid, tipo, fornitore=9, day=date(2026, 4, 29)):
    return SimpleNamespace(id=fid, tipo_documento=tipo, fornitore_id=fornitore, data_documento=day, tenant_id=1)


# ─────────────────────────────────────────────
# Fatture: elenco
# ─────────────────────────────────────────────

class InvoiceListTest(unittest.TestCase):
    def run_list(self):
        db = RecordingDb([5], [Decimal("0")], [0], [])
        asyncio.run(list_fatture(
            response=Response(), location_id=None, fornitore_id=None, tipo_documento=None, marker=None,
            data_da=None, data_a=None, search=None, limit=50, offset=0,
            current_user=SimpleNamespace(ruolo=SimpleNamespace(value="admin"), location_id=None, tenant_id=1),
            db=db,
        ))
        return [sql(s) for s in db.statements]

    def test_pagination_order_is_stable(self):
        # B9: 258 dates with more than one invoice (17 on 13/07/2026).
        page_query = self.run_list()[3]
        self.assertIn("ORDER BY fatture.data_documento DESC, fatture.id DESC", page_query)

    def test_total_subtracts_td04_and_td08(self):
        amount_query = self.run_list()[1]
        self.assertIn("'TD04'", amount_query)
        self.assertIn("'TD08'", amount_query)
        self.assertIn("THEN -1", amount_query)


# ─────────────────────────────────────────────
# Fatture: dettaglio righe
# ─────────────────────────────────────────────

class InvoiceLinesTest(unittest.TestCase):
    def lines(self, fattura, righe, *more):
        db = RecordingDb([fattura], righe, [], *more)
        result = asyncio.run(list_righe_fattura(fattura_id=fattura.id, current_user=ADMIN, db=db))
        return result, db

    def test_mini_panino_amount_uses_invoiced_price(self):
        # A4/M20: Melius 1/9738, 2 CT at 26.89 with prezzo_netto_normalizzato overwritten to 0.2689.
        riga = invoice_line(5608, "2", "CT", "26.89", pnn="0.2689")
        (out,), _ = self.lines(invoice(411, TipoDocumento.TD01), [riga])
        self.assertEqual(out.prezzo_netto_fattura, Decimal("26.89"))
        self.assertEqual(out.importo_riga.quantize(Decimal("0.01")), Decimal("53.78"))

    def test_calypso_invoice_6816_line_total(self):
        # M20: VE.MO. 6816, Calypso 6 CF at 50.09 (shown 0.93 and 5.57 before).
        riga = invoice_line(31, "6", "CF", "50.09", pnn="0.9276")
        (out,), _ = self.lines(invoice(6, TipoDocumento.TD01, fornitore=21), [riga])
        self.assertEqual(out.importo_riga.quantize(Decimal("0.01")), Decimal("300.54"))

    def test_discount_is_applied(self):
        riga = invoice_line(5766, "1", "CT", "26.8926", discount="0.01", pnn="0.2689")
        (out,), _ = self.lines(invoice(423, TipoDocumento.TD01), [riga])
        self.assertEqual(out.prezzo_netto_fattura.quantize(Decimal("0.0001")), Decimal("26.8899"))

    def test_credit_note_lines_are_negative(self):
        # M19: Navas n.146 (TD04), GIN TANQUERAY 100 CL 374 BT at 15.1639.
        riga = invoice_line(1, "374", "BT", "15.1639", pnn="15.1639")
        (out,), _ = self.lines(invoice(66, TipoDocumento.TD04, fornitore=22), [riga])
        self.assertEqual(out.importo_riga.quantize(Decimal("0.01")), Decimal("-5671.30"))
        (td08,), _ = self.lines(invoice(67, TipoDocumento.TD08, fornitore=22), [invoice_line(2, "1", "BT", "15.16")])
        self.assertEqual(td08.importo_riga, Decimal("-15.16"))

    def test_scaglioni_query_compiles_without_distinct(self):
        # A16: func.case(..., else_=...) raised TypeError -> HTTP 500.
        listino = SimpleNamespace(
            sku_interno=MINI_PANINO.sku_interno, pfa_tipo=PFATipo.scaglioni, pfa_valore=None, unita_misura=None,
            pfa_scaglioni=[
                SimpleNamespace(soglia_da=Decimal("0"), soglia_a=Decimal("1000"), valore_percentuale=Decimal("0.01")),
                SimpleNamespace(soglia_da=Decimal("1000"), soglia_a=None, valore_percentuale=Decimal("0.03")),
            ],
        )
        riga = invoice_line(5608, "2", "CT", "26.89", pnn="0.2689", sku=MINI_PANINO.sku_interno, code="PPANVE")
        (out,), db = self.lines(
            invoice(411, TipoDocumento.TD01), [riga], [listino], [(MINI_PANINO.sku_interno, Decimal("1200"))]
        )
        spent = sql(db.statements[4])
        self.assertNotIn("DISTINCT", spent.upper())
        self.assertIn("CASE WHEN", spent)
        self.assertIn("'TD08'", spent)
        self.assertIn("is_omaggio", spent)
        self.assertNotIn("prezzo_netto_normalizzato", spent)
        self.assertIn("righe_fattura.prezzo_unitario_fatturato", spent)
        self.assertEqual(out.netto_rientro, Decimal("26.89") * Decimal("0.97"))

    def test_fixed_pfa_is_converted_to_the_invoice_unit(self):
        # M22: MINI PANINO 1 CT at 26.60, PFA 0.02 per piece, carton of 100 -> Net 24.60 (not 26.58).
        listino = SimpleNamespace(
            sku_interno=MINI_PANINO.sku_interno, pfa_tipo=PFATipo.fisso, pfa_valore=Decimal("0.02"),
            unita_misura=None, pfa_scaglioni=[],
        )
        riga = invoice_line(15422, "1", "CT", "26.60", pnn="26.60", sku=MINI_PANINO.sku_interno, code="PPANVE",
                            description=MINI_PANINO_DESC)
        (out,), _ = self.lines(
            invoice(1431, TipoDocumento.TD01), [riga], [listino], [MINI_PANINO], [MINI_PANINO_ALIAS]
        )
        self.assertEqual(out.netto_rientro, Decimal("24.60"))

    def test_fixed_pfa_without_reliable_conversion_shows_no_net(self):
        bao = product(900, "SKU-BAO", "Pz", "PANE BAO")
        listino = SimpleNamespace(sku_interno="SKU-BAO", pfa_tipo=PFATipo.fisso, pfa_valore=Decimal("0.05"),
                                  unita_misura="PZ", pfa_scaglioni=[])
        riga = invoice_line(1, "1", "CT", "25.60", sku="SKU-BAO", code="X", description="PANE BAO")
        (out,), _ = self.lines(invoice(1, TipoDocumento.TD01), [riga], [listino], [bao], [])
        self.assertIsNone(out.netto_rientro)


# ─────────────────────────────────────────────
# Accordi commerciali
# ─────────────────────────────────────────────

def agreement(ag_id, fornitore, prod, unit, price, start, tipo=PFATipo.percentuale, valore="0.03",
              scaglioni=(), end=None):
    return SimpleNamespace(
        id=ag_id, fornitore_id=fornitore, sku_interno=prod.sku_interno, descrizione=prod.canonical_name,
        unita_misura=unit, prezzo_pattuito=Decimal(price), data_inizio_validita=start, data_scadenza=end,
        pfa_tipo=tipo, pfa_valore=Decimal(valore) if valore is not None else None, pfa_scaglioni=list(scaglioni),
        fornitore=SimpleNamespace(nome_azienda=f"Fornitore {fornitore}"),
    )


def factor_function(prod, aliases, agreement_unit):
    index = pl.AliasIndex(aliases)

    def factor_of(line):
        return accordi.line_factor(
            product=prod, alias=index.resolve(line.fornitore_id, prod.id, line.codice_fornitore, line.descrizione),
            unita_misura=line.unita_misura, descrizione=line.descrizione, agreement_unit=agreement_unit,
        )
    return factor_of


def calypso_rows():
    return [
        purchase_row(fornitore=21, product_obj=CALYPSO, code="BORBF54", description=CALYPSO_DESC, unit="CF",
                     qty="6", price="50.09", day=date(2026, 9, 30)),
        purchase_row(fornitore=21, product_obj=CALYPSO, code="BORBF54", description=CALYPSO_DESC, unit="CF",
                     qty="6", price="50.09", day=date(2026, 1, 30)),
        purchase_row(fornitore=21, product_obj=CALYPSO, code="BORCF", description=CALYPSO_DESC, unit="PZ",
                     qty="204", price="0.96", day=date(2026, 1, 4)),
        purchase_row(fornitore=21, product_obj=CALYPSO, code="BORBF54", description=CALYPSO_DESC, unit="CF",
                     qty="5", price="50.09", day=date(2026, 2, 26)),
        purchase_row(fornitore=21, product_obj=CALYPSO, code="BORBF54", description=CALYPSO_DESC, unit="CF",
                     qty="5", price="50.09", day=date(2026, 6, 29)),
    ]


class AgreementTotalsTest(unittest.TestCase):
    WINDOW = {"data_da": date(2026, 1, 1), "data_a": date(2026, 11, 15)}

    def test_default_window_is_current_calendar_year(self):
        self.assertEqual(accordi.default_window(None, None, date(2026, 11, 15)),
                         (date(2026, 1, 1), date(2026, 11, 15)))
        self.assertEqual(accordi.default_window(None, date(2025, 6, 30), date(2026, 11, 15)),
                         (date(2025, 1, 1), date(2025, 6, 30)))

    def test_calypso_cartons_and_pieces(self):
        # A17: shown 226 CF and 462.06 EUR, right 25.78 CF and 1297.82 EUR.
        totals = accordi.agreement_totals(
            calypso_rows(), factor_function(CALYPSO, CALYPSO_ALIASES, "CF"), **self.WINDOW
        )
        self.assertEqual(totals.quantita.quantize(Decimal("0.01")), Decimal("25.78"))
        self.assertEqual(totals.fatturato.quantize(Decimal("0.01")), Decimal("1297.82"))
        self.assertEqual(totals.righe_non_convertibili, 0)

    def test_thomas_henry_bottles_and_cartons(self):
        # A17: 72 BT + 2 CT x 24, shown 74 BT, right 120 BT.
        rows = [
            purchase_row(fornitore=22, product_obj=THOMAS, code="GINGER5", description="THOMAS HENRY GINGER BEER 200 ML",
                         unit="BT", qty="24", price="0.8196", day=day)
            for day in (date(2026, 10, 5), date(2026, 10, 7), date(2026, 7, 20))
        ] + [
            purchase_row(fornitore=22, product_obj=THOMAS, code="GINGER5", description="THOMAS HENRY GINGER BEER 200 X 24",
                         unit="CT", qty="1", price=price, day=day)
            for price, day in (("26.23", date(2026, 1, 27)), ("26.36", date(2026, 5, 28)))
        ]
        totals = accordi.agreement_totals(rows, factor_function(THOMAS, [THOMAS_ALIAS], "BT"), **self.WINDOW)
        self.assertEqual(totals.quantita, Decimal("120"))

    def test_unconvertible_line_gives_no_quantity_and_no_fixed_rebate(self):
        bao = product(900, "SKU-BAO", "Pz", "PANE BAO")
        rows = [
            purchase_row(fornitore=9, product_obj=bao, code="X", description="PANE BAO", unit="PZ", qty="60",
                         price="0.83"),
            purchase_row(fornitore=9, product_obj=bao, code="Y", description="PANE BAO", unit="CT", qty="2",
                         price="25.60"),
        ]
        totals = accordi.agreement_totals(rows, factor_function(bao, [], "PZ"), **self.WINDOW)
        self.assertIsNone(totals.quantita)
        self.assertEqual(totals.righe_non_convertibili, 1)
        self.assertEqual(totals.fatturato, Decimal("60") * Decimal("0.83") + Decimal("2") * Decimal("25.60"))
        fixed = agreement(1, 9, bao, "PZ", "0.65", date(2026, 10, 27), tipo=PFATipo.fisso, valore="0.02")
        self.assertIsNone(accordi.agreement_rebate(fixed, totals))
        percent = agreement(1, 9, bao, "PZ", "0.65", date(2026, 10, 27), tipo=PFATipo.percentuale, valore="0.03")
        self.assertEqual(accordi.agreement_rebate(percent, totals), totals.fatturato * Decimal("0.03"))

    def test_credit_note_is_subtracted(self):
        rows = calypso_rows() + [
            purchase_row(fornitore=21, product_obj=CALYPSO, code="BORBF54", description=CALYPSO_DESC, unit="CF",
                         qty="1", price="50.09", day=date(2026, 10, 1), tipo=TipoDocumento.TD08),
        ]
        totals = accordi.agreement_totals(rows, factor_function(CALYPSO, CALYPSO_ALIASES, "CF"), **self.WINDOW)
        self.assertEqual(totals.quantita.quantize(Decimal("0.01")), Decimal("24.78"))
        self.assertEqual(totals.fatturato.quantize(Decimal("0.01")), Decimal("1247.73"))

    def test_scaglioni_threshold_uses_calendar_year_spend(self):
        tiers = [
            SimpleNamespace(soglia_da=Decimal("0"), soglia_a=Decimal("1000"), valore_percentuale=Decimal("0.01")),
            SimpleNamespace(soglia_da=Decimal("1000"), soglia_a=None, valore_percentuale=Decimal("0.03")),
        ]
        rows = calypso_rows()
        totals = accordi.agreement_totals(
            rows, factor_function(CALYPSO, CALYPSO_ALIASES, "CF"), data_da=date(2026, 9, 1), data_a=date(2026, 11, 15)
        )
        self.assertEqual(totals.fatturato.quantize(Decimal("0.01")), Decimal("300.54"))
        self.assertEqual(totals.fatturato_anno.quantize(Decimal("0.01")), Decimal("1297.82"))
        ag = agreement(2000, 21, CALYPSO, "CF", "50.09", date(2026, 9, 30), tipo=PFATipo.scaglioni, valore=None,
                       scaglioni=tiers)
        self.assertEqual(accordi.agreement_rebate(ag, totals), totals.fatturato * Decimal("0.03"))
        self.assertEqual(scaglione_percentage(tiers, Decimal("300.54")), Decimal("0.01"))

    def test_one_version_per_agreement_without_start_date_filter(self):
        # 1.403 open price-list rows start on 27/10/2026 (load date): they must still count all 2026 lines.
        old = agreement(10, 21, CALYPSO, "CF", "48.00", date(2025, 1, 1), end=date(2026, 9, 29))
        current = agreement(2000, 21, CALYPSO, "CF", "50.09", date(2026, 9, 30))
        self.assertEqual(accordi.pick_agreement_versions([old, current], date(2026, 11, 15)), [current])
        self.assertEqual(accordi.pick_agreement_versions([old, current], date(2026, 6, 30)), [old])
        self.assertEqual(accordi.pick_agreement_versions([current], date(2025, 12, 31)), [current])


class AgreementEndpointTest(unittest.TestCase):
    def test_calypso_end_to_end(self):
        ag = agreement(2000, 21, CALYPSO, "CF", "50.09", date(2026, 9, 30))
        db = RecordingDb([ag], [CALYPSO], CALYPSO_ALIASES, [], [], calypso_rows())
        result = asyncio.run(accordi.list_accordi_commerciali(
            fornitore_id=None, location_id=None, data_da=date(2026, 1, 1), data_a=date(2026, 11, 15),
            current_user=ADMIN, db=db,
        ))
        (item,) = result
        self.assertEqual(item.quantita_acquistata, Decimal("25.7778"))
        self.assertEqual(item.totale_fatturato, Decimal("1297.8200"))
        self.assertEqual(item.rientro_accumulato, Decimal("38.9346"))
        self.assertFalse(item.unita_non_omogenee)
        self.assertEqual(item.periodo_da, date(2026, 1, 1))

        agreements_sql = sql(db.statements[0])
        where = agreements_sql.split("WHERE", 1)[1]
        self.assertNotIn("data_inizio_validita", where)
        self.assertIn("fornitori.archived_at IS NULL", where)
        self.assertIn("listino_master.data_scadenza >= '2026-01-01'", where)
        lines_sql = sql(db.statements[5])
        self.assertIn("'TD08'", lines_sql)
        self.assertIn("is_omaggio", lines_sql)
        self.assertIn("fatture.tenant_id", lines_sql)
        self.assertNotIn("prezzo_netto_normalizzato", lines_sql)

    def test_manager_sees_only_own_location_and_mixed_units_flag(self):
        bao = product(900, "SKU-BAO", "Pz", "PANE BAO")
        ag = agreement(300, 9, bao, "PZ", "0.65", date(2026, 10, 27), tipo=PFATipo.fisso, valore="0.02")
        rows = [
            purchase_row(fornitore=9, product_obj=bao, code="X", description="PANE BAO", unit="PZ", qty="60",
                         price="0.83", location=2),
            purchase_row(fornitore=9, product_obj=bao, code="Y", description="PANE BAO", unit="CT", qty="2",
                         price="25.60", location=1),
        ]
        manager = SimpleNamespace(id=2, ruolo=RuoloUtente.manager, location_id=1, tenant_id=1)
        db = RecordingDb([ag], [bao], [], [], [], rows)
        (item,) = asyncio.run(accordi.list_accordi_commerciali(
            fornitore_id=None, location_id=None, data_da=None, data_a=date(2026, 11, 15),
            current_user=manager, db=db,
        ))
        self.assertTrue(item.unita_non_omogenee)
        self.assertIsNone(item.quantita_acquistata)
        self.assertIsNone(item.rientro_accumulato)
        self.assertIsNone(item.netto_rientro_medio)
        self.assertEqual(item.totale_fatturato, Decimal("51.2000"))


# ─────────────────────────────────────────────
# Estrazione listino da fatture
# ─────────────────────────────────────────────

def panino_rows():
    return [
        purchase_row(fornitore=9, product_obj=MINI_PANINO, code="PPANVE", description=MINI_PANINO_DESC, unit="CT",
                     qty=qty, price=price, discount=discount)
        for qty, price, discount in PANINO_EDNA_ROWS
    ]


def conversions_for(rows, products, aliases):
    keys = {pl.conversion_key(r) for r in rows}
    return pl.compute_conversions(keys, {p.id: p for p in products}, pl.AliasIndex(aliases))


class InvoicePriceListExtractionTest(unittest.TestCase):
    def test_panino_edna_average_and_minimum_per_carton(self):
        # M21: shown minimum 0.2590 and average 23.8734; right 25.90 and 26.6605 (171 CT).
        rows = panino_rows()
        conversions = conversions_for(rows, [MINI_PANINO], [MINI_PANINO_ALIAS])
        (avg,) = group_invoice_price_lines(rows, conversions, "MELIUS", "avg")
        self.assertEqual(avg["prezzo_pattuito"], 26.6605)
        self.assertEqual(avg["unita_misura"], "CT")
        self.assertEqual(avg["totale_acquistato"], 171.0)
        self.assertEqual(avg["occorrenze"], 66)
        (minimum,) = group_invoice_price_lines(rows, conversions, "MELIUS", "min")
        self.assertEqual(minimum["prezzo_pattuito"], 25.9)
        (latest,) = group_invoice_price_lines(rows, conversions, "MELIUS", "latest")
        self.assertEqual(latest["prezzo_pattuito"], 26.89)

    def test_same_sku_is_one_item_per_package(self):
        # M21: KITO SACCHI 130X150 came out in 5 rows (CT / CNF / CNF / CT / PZ).
        rows = [
            purchase_row(fornitore=24, product_obj=SACCHI, code=None, description=SACCHI_DESC, unit=unit, qty=qty,
                         price=price, day=date.fromisoformat(day))
            for day, qty, unit, price in sorted(SACCHI_KITO_ROWS, key=lambda r: r[0], reverse=True)
        ]
        conversions = conversions_for(rows, [SACCHI], SACCHI_ALIASES)
        items = group_invoice_price_lines(rows, conversions, "KITO SRL", "min")
        by_unit = {item["unita_misura"]: item for item in items}
        self.assertEqual(sorted(by_unit), ["CT", "PZ"])
        self.assertEqual(by_unit["CT"]["occorrenze"], 27)
        self.assertEqual(by_unit["CT"]["prezzo_pattuito"], 22.5)
        self.assertEqual(by_unit["PZ"]["prezzo_pattuito"], 23.5)
        self.assertTrue(all(item["sku_interno"] == SACCHI.sku_interno for item in items))

    def test_unknown_unit_is_not_guessed(self):
        row = purchase_row(fornitore=9, product_obj=None, code=None, description="TRASPORTO", unit=None, qty="1",
                           price="15")
        (item,) = group_invoice_price_lines([row], {}, "MELIUS", "latest")
        self.assertEqual(item["unita_misura"], "")

    def test_extraction_query_uses_shared_base(self):
        rows = panino_rows()
        key = pl.conversion_key(rows[0])
        db = RecordingDb([tuple(key)], [MINI_PANINO], [MINI_PANINO_ALIAS], rows)
        fornitore = SimpleNamespace(id=9, nome_azienda="MELIUS")
        (item,) = asyncio.run(extract_invoice_price_items(db, ADMIN, fornitore, "avg"))
        self.assertEqual(item["prezzo_pattuito"], 26.6605)
        rows_sql = sql(db.statements[-1])
        self.assertNotIn("prezzo_netto_normalizzato", rows_sql)
        self.assertIn("righe_escluse_statistiche", rows_sql)
        self.assertIn("fatture.tenant_id", rows_sql)
        self.assertIn("ORDER BY righe_listino.data_documento DESC, righe_listino.riga_id DESC", rows_sql)


if __name__ == "__main__":
    unittest.main()
