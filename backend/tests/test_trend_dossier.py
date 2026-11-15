"""Trend prezzi (Oscillazioni, ValidationRoom) e dossier Excel di contestazione.

Casi reali del rapporto schermate del 14/11/2026 (export di produzione):
Spiedini bamboo CAN-21-494 (4 righe, una nota di credito), PANE BAO MELIUS
(cartone da 30 contro listino a pezzo 0,65, anomalia 300), RUSTICI MIGNON
(kg con fattore 0,2 contro listino a cartone 26,80, anomalia 302), anomalie
171, 263, 300, 301, 302 per il dossier. Nessun database.
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

import openpyxl  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.anomalie import comparison_quantity  # noqa: E402
from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import dispute_dossier as dd  # noqa: E402
from app.services import price_trend as pt  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402
from app.services.purchase_lines import AliasIndex  # noqa: E402

ADMIN = SimpleNamespace(id=1, ruolo=SimpleNamespace(value="admin"), location_id=None, tenant_id=1)
MANAGER = SimpleNamespace(id=2, ruolo=SimpleNamespace(value="manager"), location_id=3, tenant_id=1)
TODAY = date(2026, 11, 14)


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def product(pid, sku, unit, name):
    return Product(id=pid, sku_interno=sku, canonical_name=name, comparison_unit=unit, unit_count=1)


def alias(aid, supplier, pid, code, description, pack=None, fattore=None, weight_g=None):
    return SupplierProductAlias(
        id=aid, supplier_id=supplier, product_id=pid, supplier_code=code, raw_description=description,
        normalized_description=normalize_text(description), pack_qty=pack, fattore_confezione=fattore,
        weight_g=weight_g, status="approved", source="manual",
    )


def listino(lid, forn, sku, price, unit, start, end=None, alias_id=None):
    return SimpleNamespace(id=lid, fornitore_id=forn, sku_interno=sku, prezzo_pattuito=Decimal(price),
                           unita_misura=unit, data_inizio_validita=start, data_scadenza=end,
                           supplier_product_alias_id=alias_id)


def line(rid, day, tipo, forn, sku, pid, code, desc, qty, uom, price, discount="0", fornitore="F"):
    return SimpleNamespace(
        riga_id=rid, fattura_id=rid, numero_documento=f"N{rid}", data_documento=day, tipo_documento=tipo,
        location_id=1, fornitore_id=forn, sku_interno=sku, product_id=pid, codice_fornitore=code,
        descrizione=desc, unita_misura=uom, quantita=Decimal(qty), prezzo_unitario=Decimal(price),
        sconto_percentuale=Decimal(discount), fornitore_nome=fornitore, location_nome="FIORDACQUA SRL",
    )


# ── Dati reali ──
SPIEDINI_SKU = "CAN-21-494-1793543248"
SPIEDINI = product(689, SPIEDINI_SKU, "Pz", "Spiedini in bamboo con ricciolo nero cm 12 100 pezzi")
SPIEDINI_ALIASES = [
    alias(2044, 21, 689, "ALM02543", "Spiedini in bamboo con ricciolo nero cm 12 100 pezzi ALM02543"),
    alias(3582, 21, 689, "LEOSBR", "Spiedini in bamboo con ricciolo cm 12 100 pezzi S0015"),
    alias(4937, 6, 689, "00147", "LEONE SPIEDI RICCIOLO 100PZ S0015"),
]
SPIEDINI_LISTINI = {21: [listino(2044, 21, SPIEDINI_SKU, "2.81", "CF", date(2026, 1, 9), alias_id=2044)]}
SPIEDINI_LINES = [
    line(494, date(2026, 1, 9), "TD01", 21, SPIEDINI_SKU, 689, "ALM02543",
         "Spiedini in bamboo con ricciolo nero cm 12 100 pezzi ALM02543", "100", "CF", "2.81"),
    line(2, date(2026, 1, 20), "TD04", 21, SPIEDINI_SKU, 689, "ALM02543",
         "Spiedini in bamboo con ricciolo nero cm 12 100 pezzi ALM02543", "50", "CF", "2.81"),
    line(12549, date(2026, 7, 21), "TD01", 6, SPIEDINI_SKU, 689, "00147",
         "LEONE SPIEDI RICCIOLO 100PZ S0015", "3", "PZ", "3.10"),
    line(6492, date(2026, 9, 24), "TD01", 21, SPIEDINI_SKU, 689, "LEOSBR",
         "Spiedini in bamboo con ricciolo cm 12 100 pezzi S0015", "50", "CF", "2.80"),
]

BAO_SKU = "SG3-80E96D7103B1CF44"
BAO = product(7, BAO_SKU, "Pz", "PANE BAO")
BAO_DESC = "PANE BAO EUROPASTRY 40grx30pz surg."
BAO_ALIASES = [alias(29, 9, 7, None, BAO_SKU), alias(2520, 9, 7, "SVHAPHO", BAO_DESC, pack=30)]
# Listini aperti di quattro fornitori dal 27/10/2026: solo il MELIUS (9) vale per le righe MELIUS.
BAO_LISTINI = {
    15: [listino(28, 15, BAO_SKU, "0.50", None, date(2026, 10, 27), alias_id=28)],
    9: [listino(29, 9, BAO_SKU, "0.65", None, date(2026, 10, 27), alias_id=29)],
    16: [listino(30, 16, BAO_SKU, "0.45", None, date(2026, 10, 27), alias_id=30)],
    13: [listino(31, 13, BAO_SKU, "0.70", None, date(2026, 10, 27), alias_id=31)],
}

RUSTICI_SKU = "SG3-708D37CADADD63FF"
RUSTICI = product(190, RUSTICI_SKU, "Ct", "RUSTICI MISTI MIGNON RISPO")
RUSTICI_DESC = "RUSTICI MIGNON RISPO 7 GUSTI GR20 C. 2X2.5KG"
RUSTICI_ALIAS = alias(2525, 9, 190, "SVRRUSMI", RUSTICI_DESC, fattore=Decimal("0.2000"), weight_g=2500)
RUSTICI_LISTINI = {
    9: [listino(750, 9, RUSTICI_SKU, "26.80", "CT", date(2026, 10, 27), alias_id=750)],
    13: [listino(751, 13, RUSTICI_SKU, "11.50", None, date(2026, 10, 27), alias_id=751)],
}


def points(lines, products, aliases, listini):
    index = AliasIndex(aliases)
    result = []
    for row in lines:
        result.append(pt.trend_point(
            row,
            product=products.get(row.product_id),
            alias=index.resolve(row.fornitore_id, row.product_id, row.codice_fornitore, row.descrizione),
            supplier_listini=listini.get(row.fornitore_id, ()),
            today=TODAY,
        ))
    return result


class KeywordTest(unittest.TestCase):
    def test_technical_codes_give_no_keywords(self):
        # r"\\d" cercava un backslash: CAN-21-494 diventava ["can"] e il trend prendeva 7.117 righe.
        self.assertEqual(pt.extract_informative_keywords("CAN-21-494-1793543248"), [])
        self.assertEqual(pt.extract_informative_keywords("SG3-BB0E08B60A26BBA2"), [])
        self.assertEqual(pt.extract_informative_keywords("SKU-TON23011-201"), [])

    def test_descriptions_still_give_keywords(self):
        self.assertEqual(pt.extract_informative_keywords("Acqua Electa naturale"), ["acqua", "electa", "naturale"])


class TrendQueryTest(unittest.TestCase):
    def test_series_contains_only_lines_of_that_sku(self):
        text = sql(pt.trend_lines_select(ADMIN, [SPIEDINI_SKU]))
        self.assertIn("righe_fattura.sku_interno IN", text)
        self.assertNotIn("LIKE", text.upper())
        self.assertNotIn("descrizione_fornitore_raw) IN", text)
        self.assertIn("stato_matching", text)
        # regole comuni: SKU esclusi, righe escluse, tenant
        self.assertIn("skus_esclusi", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("tenant_id", text)


class SpiediniTest(unittest.TestCase):
    def setUp(self):
        self.points = points(SPIEDINI_LINES, {689: SPIEDINI}, SPIEDINI_ALIASES, SPIEDINI_LISTINI)

    def test_four_points_and_the_return_is_marked(self):
        self.assertEqual(len(self.points), 4)
        returns = [p for p in self.points if p["is_reso"]]
        self.assertEqual([p["riga_id"] for p in returns], [2])
        self.assertEqual(returns[0]["tipo_documento"], "TD04")

    def test_each_supplier_in_its_own_price_list_unit(self):
        by_row = {p["riga_id"]: p for p in self.points}
        self.assertEqual((by_row[494]["prezzo_pagato"], by_row[494]["unita_confronto"]), (2.81, "CT"))
        self.assertEqual(by_row[494]["prezzo_contratto"], 2.81)
        self.assertEqual((by_row[12549]["prezzo_pagato"], by_row[12549]["unita_confronto"]), (3.1, "Pz"))
        self.assertIsNone(by_row[12549]["prezzo_contratto"])

    def test_two_suppliers_have_no_single_current_contract(self):
        summary = pt.series_summary(SPIEDINI_SKU, product=SPIEDINI, history=self.points,
                                    listini_by_supplier=SPIEDINI_LISTINI, requested_suppliers=None, today=TODAY)
        self.assertIsNone(summary["prezzo_contratto_corrente"])
        self.assertEqual({f["fornitore_id"] for f in summary["fornitori"]}, {21, 6})


class PaneBaoTest(unittest.TestCase):
    def setUp(self):
        lines = [
            line(5939, date(2026, 10, 8), "TD01", 9, BAO_SKU, 7, "SVHAPHO", BAO_DESC, "2", "CT", "24.89", fornitore="MELIUS"),
            line(15376, date(2026, 10, 27), "TD01", 9, BAO_SKU, 7, "SVHAPHO", BAO_DESC, "2", "CT", "24.92", fornitore="MELIUS"),
        ]
        self.points = points(lines, {7: BAO}, BAO_ALIASES, BAO_LISTINI)

    def test_point_converted_per_piece_against_melius_list(self):
        last = self.points[-1]
        self.assertEqual(last["prezzo_pagato"], 0.8307)  # = snapshot dell'anomalia 300
        self.assertEqual(last["unita_confronto"], "Pz")
        self.assertEqual(last["prezzo_contratto"], 0.65)  # MELIUS, non 0,70 di un altro fornitore
        self.assertEqual((last["prezzo_fattura"], last["unita_fattura"]), (24.92, "CT"))
        self.assertEqual(last["quantita_confronto"], 60.0)

    def test_no_contract_before_the_price_list_starts(self):
        first = self.points[0]
        self.assertTrue(first["confrontabile"])
        self.assertIsNone(first["prezzo_contratto"])  # il listino parte il 27/10/2026

    def test_current_contract_of_the_only_supplier(self):
        summary = pt.series_summary(BAO_SKU, product=BAO, history=self.points, listini_by_supplier=BAO_LISTINI,
                                    requested_suppliers=[9], today=TODAY)
        self.assertEqual((summary["prezzo_contratto_corrente"], summary["unita_contratto_corrente"]), (0.65, "Pz"))

    def test_without_purchases_suppliers_with_a_list_are_listed(self):
        summary = pt.series_summary(BAO_SKU, product=BAO, history=[], listini_by_supplier=BAO_LISTINI,
                                    requested_suppliers=None, today=TODAY)
        self.assertIsNone(summary["prezzo_contratto_corrente"])
        self.assertEqual(len(summary["fornitori"]), 4)


class RusticiTest(unittest.TestCase):
    def test_kg_line_converted_to_carton_with_the_link_factor(self):
        row = line(15429, date(2026, 11, 10), "TD01", 9, RUSTICI_SKU, 190, "SVRRUSMI", RUSTICI_DESC, "5", "KG", "6.26")
        point = points([row], {190: RUSTICI}, [RUSTICI_ALIAS], RUSTICI_LISTINI)[0]
        self.assertEqual((point["prezzo_pagato"], point["unita_confronto"]), (31.3, "CT"))
        self.assertEqual(point["prezzo_contratto"], 26.8)  # non 11,50 del fornitore 13
        self.assertEqual(point["quantita_confronto"], 1.0)


class UnreliableConversionTest(unittest.TestCase):
    def test_carton_without_known_pack_stays_in_invoice_unit(self):
        voce = product(900, "SG3-TEST", "Pz", "Voce a pezzo")
        row = line(1, date(2026, 11, 1), "TD01", 9, "SG3-TEST", 900, None, "Voce senza confezione", "2", "CT", "12.00")
        point = points([row], {900: voce}, [], {})[0]
        self.assertFalse(point["confrontabile"])
        self.assertIsNone(point["prezzo_pagato"])
        self.assertEqual((point["prezzo_fattura"], point["unita_fattura"]), (12.0, "CT"))


class ListinoValidAtTest(unittest.TestCase):
    def test_two_lists_valid_together_are_ambiguous(self):
        items = [listino(1, 22, "X", "3.20", None, date(2026, 10, 27)), listino(2, 22, "X", "4.508", "CT", date(2026, 10, 20))]
        self.assertIsNone(pt.listino_valid_at(items, date(2026, 10, 30)))
        self.assertEqual(pt.listino_valid_at(items, date(2026, 10, 21)).id, 2)
        self.assertIsNone(pt.listino_valid_at(items, date(2026, 10, 1)))

    def test_the_line_alias_wins(self):
        items = [listino(1, 22, "X", "3.20", None, date(2026, 10, 27), alias_id=5),
                 listino(2, 22, "X", "4.50", None, date(2026, 10, 27), alias_id=6)]
        self.assertEqual(pt.listino_valid_at(items, date(2026, 11, 1), alias_id=6).id, 2)

    def test_series_unit_prefers_the_open_list(self):
        items = [listino(1215, 22, "X", "3.20", None, date(2026, 10, 27), end=date(2026, 11, 5)),
                 listino(2868, 22, "X", "4.508", "CT", date(2026, 10, 20))]
        self.assertEqual(pt.series_unit(items, TODAY), "CT")


# ── Dossier ──
def anomaly(aid, delta_prezzo, delta_totale, listino_price, fatturato):
    return SimpleNamespace(id=aid, delta_prezzo=Decimal(delta_prezzo), delta_totale=Decimal(delta_totale),
                           prezzo_listino_snapshot=Decimal(listino_price), prezzo_fatturato_snapshot=Decimal(fatturato))


def riga(sku, desc, qty, uom):
    return SimpleNamespace(sku_interno=sku, descrizione_fornitore_raw=desc, quantita=Decimal(qty), unita_misura_fattura=uom)


def fattura(day, numero):
    return SimpleNamespace(data_documento=day, numero_documento=numero)


DOSSIER_ROWS = [
    dd.dossier_row(anomaly(171, "0.7800", "23.4000", "7.2000", "7.9800"),
                   riga("CAN-9-5683-1793803198", "SEPPIE INDIA PUL.U1 IQF", "30", "KG"),
                   fattura(date(2026, 10, 13), "1/28873"), "MELIUS CATERING S.P.A.", "LIDO PLAYALUNA SRL", "Kg"),
    dd.dossier_row(anomaly(263, "1.3000", "12.5450", "24.0000", "25.3000"),
                   riga("CAN-9-5884-1793803197", "CUBEROLL DANISH CROWN FR. S/V", "9.65", "KG"),
                   fattura(date(2026, 10, 3), "1/27990"), "MELIUS CATERING S.P.A.", "FIORDACQUA SRL", "Kg"),
    dd.dossier_row(anomaly(300, "0.1807", "10.8420", "0.6500", "0.8307"),
                   riga(BAO_SKU, BAO_DESC, "2", "CT"), fattura(date(2026, 10, 27), "1/30136"),
                   "MELIUS CATERING S.P.A.", "FIORDACQUA SRL", "Pz"),
    dd.dossier_row(anomaly(301, "0.0160", "1.6000", "0.2500", "0.2660"),
                   riga("SG3-52506F3CBE1143E1", "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO", "1", "CT"),
                   fattura(date(2026, 11, 5), "1/30906"), "MELIUS CATERING S.P.A.", "FIORDACQUA SRL", "Pz"),
    dd.dossier_row(anomaly(302, "4.5000", "4.5000", "26.8000", "31.3000"),
                   riga(RUSTICI_SKU, RUSTICI_DESC, "5", "KG"), fattura(date(2026, 11, 10), "1/31305"),
                   "MELIUS CATERING S.P.A.", "FIORDACQUA SRL", "CT"),
]


class DossierTest(unittest.TestCase):
    def test_total_is_the_sum_of_anomaly_overcharges(self):
        self.assertEqual(dd.dossier_total(DOSSIER_ROWS), Decimal("52.8870"))

    def test_quantity_in_the_price_list_unit(self):
        by_id = {row.anomalia_id: row for row in DOSSIER_ROWS}
        self.assertEqual(by_id[300].quantita_confronto, Decimal("60"))   # 2 CT da 30 pezzi
        self.assertEqual(by_id[301].quantita_confronto, Decimal("100"))  # 1 CT da 100
        self.assertEqual(by_id[302].quantita_confronto, Decimal("1"))    # 5 kg = 1 cartone
        for row in DOSSIER_ROWS:
            self.assertEqual((row.delta_prezzo * row.quantita_confronto).quantize(Decimal("0.01")),
                             row.delta_totale.quantize(Decimal("0.01")))

    def test_workbook_total_matches(self):
        wb = openpyxl.load_workbook(BytesIO(dd.build_dossier_workbook(DOSSIER_ROWS).getvalue()))
        ws = wb["Rincari da contestare"]
        self.assertEqual(ws.max_row, len(DOSSIER_ROWS) + 2)
        self.assertEqual(ws.cell(row=ws.max_row, column=1).value, "TOTALE")
        self.assertAlmostEqual(ws.cell(row=ws.max_row, column=14).value, 52.887, places=4)
        detail_sum = sum(ws.cell(row=r, column=14).value for r in range(2, ws.max_row))
        self.assertAlmostEqual(detail_sum, 52.887, places=4)
        summary = wb["Riepilogo fornitori"]
        self.assertAlmostEqual(summary.cell(row=summary.max_row, column=4).value, 52.887, places=4)

    def test_empty_dossier(self):
        wb = openpyxl.load_workbook(BytesIO(dd.build_dossier_workbook([]).getvalue()))
        self.assertEqual(wb["Rincari da contestare"].cell(row=2, column=14).value, 0)

    def test_comparison_quantity_without_unit_delta_keeps_invoice_quantity(self):
        self.assertEqual(comparison_quantity(Decimal("0"), Decimal("0"), Decimal("5")), Decimal("5"))

    def test_same_filters_as_the_anomaly_list(self):
        text = sql(dd.select(dd.Anomalia).where(*dd.visible_anomaly_conditions(MANAGER, dd.StatoValidazione.da_verificare)))
        self.assertIn("skus_esclusi", text)          # non "sku_esclusi" (errore SQL della bozza)
        self.assertIn("tenant_id", text)
        self.assertIn("stato_validazione", text)
        self.assertIn("fatture.location_id", text)   # sede del manager
        self.assertNotIn("fatture.location_id", sql(dd.select(dd.Anomalia).where(*dd.visible_anomaly_conditions(ADMIN))))


class RemovedEndpointsTest(unittest.TestCase):
    def test_dead_endpoints_are_gone_and_dossier_needs_only_login(self):
        from app.api.v1 import intelligence
        paths = {route.path for route in intelligence.router.routes}
        for removed in ("/pricing-audit", "/cross-supplier", "/cross-location", "/export-vendor-passport/{fornitore_id}"):
            self.assertNotIn(removed, paths)
        self.assertIn("/export-dispute-excel", paths)
        route = next(r for r in intelligence.router.routes if r.path == "/export-dispute-excel")
        deps = {d.call.__name__ for d in route.dependant.dependencies}
        self.assertIn("get_current_user", deps)
        self.assertNotIn("require_admin", deps)


if __name__ == "__main__":
    unittest.main()
