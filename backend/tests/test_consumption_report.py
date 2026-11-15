"""Consumi per prodotto e Top prodotti (services/consumption_report.py e api/v1/intelligence.py).

Casi reali dall'export di produzione del 14/11/2026 (rapporto schermate, gruppi
CONSUMI e TOPPROD): reso Navas n.146 di Tanqueray, olio girasole in litri e in
latte da 5 L, Calypso a confezione da 54 e a pezzo, sacchi ambra a cartone/kg/pezzo,
THREE CENTS TONIC con solo un reso, unità vuota di Naonis Jader. Nessun database.
"""
import asyncio
import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import consumption_report as cr  # noqa: E402
from app.services import purchase_lines as pl  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402


def product(pid, sku, unit, name, unit_count=1, volume_ml=None):
    return Product(id=pid, sku_interno=sku, canonical_name=name, comparison_unit=unit, unit_count=unit_count,
                   volume_ml=volume_ml, is_active=True)


def alias(aid, supplier, pid, code, description, pack=None, volume_ml=None):
    return SupplierProductAlias(id=aid, supplier_id=supplier, product_id=pid, supplier_code=code,
                                raw_description=description, normalized_description=normalize_text(description),
                                pack_qty=pack, volume_ml=volume_ml, status="approved", source="manual")


TANQUERAY = product(276, "SG3-47E8AE1C5B82B9CB", "Pz", "GIN TANQUERAY LT 1")
OLIO = product(58, "SG3-55FE5E10318B7F06", "Lt", "OLIO GIRASOLE")
CALYPSO = product(645, "CAN-21-31-1793543247", "Pz", "Calypso calice fluttino bicchiere 113ml 54 pezzi")
SACCHI = product(576, "SG3-165D17EA2619C309", "CT", "SACCHI X RAC. RIFIUTI MIS. 90X120 COL. AMBRA")
TONIC = product(900, "CAN-22-642-1793794765", "Pz", "THREE CENTS TONIC WATER 20 CL")
NAONIS = product(901, "SG3-113F5FB50B5BF292", "Pz", "NAONIS JADER CUVEE BRUT 75CL")
MINI_PANINO = product(1, "SG3-52506F3CBE1143E1", "Pz", "MINI PANINO EDNA BURGHER")
PRODUCTS = {p.id: p for p in (TANQUERAY, OLIO, CALYPSO, SACCHI, TONIC, NAONIS, MINI_PANINO)}
ALIASES = pl.AliasIndex([
    alias(2243, 22, 276, "GIN0001", "GIN TANQUERAY 100 CL", volume_ml=1000),
    alias(2522, 9, 58, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", volume_ml=5000),
    alias(2600, 9, 58, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", volume_ml=20000),
    alias(2000, 21, 645, "BORBF54", "Calypso calice fluttino bicchiere 113ml 54 pezzi", pack=54, volume_ml=113),
    alias(2245, 21, 645, "BORCF", "Calypso calice fluttino bicchiere 113ml", pack=54, volume_ml=113),
])

_ids = iter(range(1, 100000))


def line(prod, fornitore, code, description, uom, qty, price, discount="0", tipo="TD01", fattura=None,
         giorno=date(2026, 3, 1), location="LIDO PLAYALUNA", fornitore_nome="Navas", omaggio=False):
    """Una riga come la restituisce consumption_report.lines_select()."""
    q, pu, sc = Decimal(qty), Decimal(price), Decimal(discount)
    net = pl.line_net_unit_price(pu, sc)
    segno = pl.document_sign(tipo)
    riga = next(_ids)
    return SimpleNamespace(
        riga_id=riga, fattura_id=fattura or riga, numero_documento=str(fattura or riga), data_documento=giorno,
        tipo_documento=tipo, location_id=1, fornitore_id=fornitore, sku_interno=prod.sku_interno,
        product_id=prod.id, comparison_unit=prod.comparison_unit, codice_fornitore=code, descrizione=description,
        unita_misura=uom, unita=pl.normalized_unit(uom), quantita=q, prezzo_unitario=pu, sconto_percentuale=sc,
        netto_unitario=net, segno=segno, quantita_firmata=segno * q, importo_netto=segno * net * q,
        is_omaggio=pl.is_free_line(omaggio, pu, sc), in_media=pl.counts_for_average(omaggio, pu, sc, tipo),
        nome_voce=prod.canonical_name, location_nome=location, fornitore_nome=fornitore_nome,
    )


def conversions(rows):
    return pl.compute_conversions({pl.conversion_key(r) for r in rows}, PRODUCTS, ALIASES)


# ── Dati reali ──
TQ = ("GIN0001", "GIN TANQUERAY 100 CL")
TANQUERAY_2026 = [
    line(TANQUERAY, 22, *TQ, "BT", "6", "15.1633", giorno=date(2026, 3, 12), fattura=6399),
    line(TANQUERAY, 22, *TQ, "BT", "1", "15.16", tipo="TD04", giorno=date(2026, 4, 2), fattura=138),
    line(TANQUERAY, 22, *TQ, "BT", "374", "15.1639", tipo="TD04", giorno=date(2026, 5, 6), fattura=146),
    line(TANQUERAY, 22, *TQ, "BT", "12", "13.3033", giorno=date(2026, 10, 7), fattura=29039),
]
OLIO_2026 = [
    line(OLIO, 9, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT", "2220", "1.81", fornitore_nome="MELIUS"),
    line(OLIO, 9, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", "LT", "3720", "1.80", fornitore_nome="MELIUS"),
    line(OLIO, 9, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", "NR", "6", "8.27", fornitore_nome="DAC"),
]
CAL_CF = ("BORBF54", "Calypso calice fluttino bicchiere 113ml 54 pezzi")
CALYPSO_2026 = [
    line(CALYPSO, 21, *CAL_CF, "CF", "6", "50.09", fornitore_nome="VE.MO."),
    line(CALYPSO, 21, *CAL_CF, "CF", "6", "50.09", fornitore_nome="VE.MO."),
    line(CALYPSO, 21, *CAL_CF, "CF", "5", "50.09", fornitore_nome="VE.MO."),
    line(CALYPSO, 21, *CAL_CF, "CF", "5", "50.09", fornitore_nome="VE.MO."),
    line(CALYPSO, 21, "BORCF", "Calypso calice fluttino bicchiere 113ml", "PZ", "204", "0.96", fornitore_nome="VE.MO."),
]
SACCHI_2026 = [
    line(SACCHI, 21, "VIABA90120", "Buste ambra N.U. PE/LD cm 90x120h 18kg", "CT", "4", "25.74"),
    line(SACCHI, 21, "VIABA90120", "Buste ambra N.U. PE/LD cm 90x120h 18kg", "CT", "2", "30.42"),
    line(SACCHI, 24, None, "SACCHI X RAC. RIFIUTI MIS. 90X120 COL. AMBRA", "CNF", "2", "22.50"),
    line(SACCHI, 6, "00141", "N.U 90X120 AMBRA", "KG", "30", "1.5667", "0.0021"),
    line(SACCHI, 3, "2913", "SACCHI AMBRA 90X120 18KG", "PZ", "2", "22.50"),
]
TONIC_RESO = [line(TONIC, 22, "CENTS6", "THREE CENTS TONIC WATER 20 CL", "BT", "216", "1.1066", tipo="TD04",
                   fattura=146)]


def by_sku(rows):
    return {item["sku_interno"]: item for item in cr.aggregate_by_sku(rows, conversions(rows))}


class CreditNotesTest(unittest.TestCase):
    def test_tanqueray_2026_is_minus_357_bottles(self):
        item = by_sku(TANQUERAY_2026)[TANQUERAY.sku_interno]
        self.assertEqual(item["quantita_totale"], -357.0)          # era 393 BT
        self.assertEqual(item["unita_misura"], "BT")
        self.assertAlmostEqual(item["spesa_totale"], -5435.84, places=2)  # era 5.937,08
        self.assertEqual(item["quantita_resa"], 375.0)
        self.assertEqual(item["numero_fatture"], 2)                 # i resi non sono acquisti
        # Prezzo medio solo sui 2 acquisti: (6 x 15,1633 + 12 x 13,3033) / 18
        self.assertAlmostEqual(item["prezzo_medio"], 13.9233, places=4)
        self.assertEqual(item["quantita_testo"], "-357 BT")

    def test_td08_is_a_credit_note_too(self):
        rows = [line(TANQUERAY, 22, *TQ, "BT", "10", "15"), line(TANQUERAY, 22, *TQ, "BT", "4", "15", tipo="TD08")]
        item = by_sku(rows)[TANQUERAY.sku_interno]
        self.assertEqual(item["quantita_totale"], 6.0)
        self.assertAlmostEqual(item["spesa_totale"], 90.0)

    def test_monthly_chart_has_the_return_negative(self):
        detail = cr.consumption_detail(TANQUERAY_2026, conversions(TANQUERAY_2026))
        months = {m["mese"]: m["quantita_totale"] for m in detail["consumo_per_mese"]}
        self.assertEqual(months["2026-05"], -374.0)                  # era +374
        self.assertEqual([m["mese"] for m in detail["consumo_per_mese"]], ["2026-10", "2026-05", "2026-04", "2026-03"])
        self.assertAlmostEqual(detail["spesa_totale"], -5435.84, places=2)
        self.assertEqual(detail["consumo_per_location"][0]["quantita_totale"], -357.0)

    def test_return_only_product_stays_with_zero_invoices(self):
        # THREE CENTS TONIC: una sola riga ed è un reso. Resta in elenco, la spesa la sottrae.
        rows = TONIC_RESO + TANQUERAY_2026
        item = by_sku(rows)[TONIC.sku_interno]
        self.assertTrue(item["solo_resi"])
        self.assertEqual(item["numero_fatture"], 0)
        self.assertAlmostEqual(item["spesa_totale"], -239.03, places=2)
        self.assertIsNone(item["prezzo_medio"])
        top = cr.top_products(cr.aggregate_by_sku(rows, conversions(rows)), "spesa", 1)
        self.assertEqual(len(top["prodotti"]), 1)
        self.assertAlmostEqual(top["totale_spesa"], sum(float(r.importo_netto) for r in rows), places=6)
        self.assertLess(top["totale_spesa"], -5674)  # nessun reso perso (-239,03 - 5.435,84)


class UnitsTest(unittest.TestCase):
    def test_oil_is_5970_litres(self):
        item = by_sku(OLIO_2026)[OLIO.sku_interno]
        self.assertEqual(item["quantita_totale"], 5970.0)           # era "5.946 PZ"
        self.assertEqual(item["unita_misura"], "Lt")
        self.assertTrue(item["conversione_completa"])
        self.assertEqual(item["fornitori"], "DAC, MELIUS")

    def test_calypso_is_1392_pieces_at_0_93(self):
        item = by_sku(CALYPSO_2026)[CALYPSO.sku_interno]
        self.assertEqual(item["quantita_totale"], 1392.0)           # era "226 PZ"
        self.assertEqual(item["unita_misura"], "Pz")
        self.assertAlmostEqual(item["spesa_totale"], 1297.82, places=2)
        self.assertAlmostEqual(item["prezzo_medio"], 1297.82 / 1392, places=6)  # 0,93 e non 2,04
        self.assertEqual(round(item["prezzo_medio"], 2), 0.93)

    def test_unreliable_units_stay_separate(self):
        item = by_sku(SACCHI_2026)[SACCHI.sku_interno]
        # Cartoni e confezioni nell'unità della voce; kg e pezzi senza fattore restano a parte.
        self.assertIsNone(item["quantita_totale"])
        self.assertIsNone(item["unita_misura"])
        self.assertIsNone(item["prezzo_medio"])
        parts = {(p["unita"], p["convertita"]): p for p in item["quantita_per_unita"]}
        self.assertEqual(parts[("CT", True)]["quantita"], 8.0)
        self.assertEqual(parts[("KG", False)]["quantita"], 30.0)
        self.assertEqual(parts[("PZ", False)]["quantita"], 2.0)
        # Il prezzo al kg (1,57) non diventa il minimo dei cartoni.
        self.assertEqual(parts[("CT", True)]["prezzo_minimo"], 22.5)
        self.assertAlmostEqual(parts[("KG", False)]["prezzo_minimo"], 1.5667, places=3)
        self.assertEqual(item["quantita_testo"], "8 CT + 30 KG (non convertito) + 2 PZ (non convertito)")

    def test_empty_unit_is_not_pieces(self):
        rows = [line(NAONIS, 30, None, "NAONIS JADER CUVEE BRUT 75CL", "", "768", "3")]
        item = by_sku(rows)[NAONIS.sku_interno]
        self.assertEqual(item["unita_misura"], "N.D.")              # era "Pz"
        self.assertEqual(item["quantita_totale"], 768.0)

    def test_name_is_the_catalogue_name(self):
        item = by_sku(OLIO_2026)[OLIO.sku_interno]
        self.assertEqual(item["descrizione"], "OLIO GIRASOLE")      # non "OLIO GIRASOLE SORRENTO 5LT"

    def test_multi_sku_detail_hides_prices_with_different_units(self):
        rows = OLIO_2026 + SACCHI_2026
        detail = cr.consumption_detail(rows, conversions(rows))
        self.assertEqual(detail["numero_prodotti"], 2)
        self.assertIsNone(detail["unita_misura"])
        self.assertIsNone(detail["quantita_totale"])
        self.assertIsNone(detail["prezzo_minimo"])
        self.assertIsNone(detail["prezzo_massimo"])
        self.assertIsNone(detail["prezzo_medio"])
        location = detail["consumo_per_location"][0]
        self.assertIsNone(location["quantita_totale"])
        self.assertIn({"unita": "Lt", "convertita": True, "quantita": 5970.0}, location["quantita_per_unita"])

    def test_single_sku_detail_prices_per_comparison_unit(self):
        detail = cr.consumption_detail(CALYPSO_2026, conversions(CALYPSO_2026))
        self.assertEqual(detail["unita_misura"], "Pz")
        self.assertAlmostEqual(detail["prezzo_minimo"], 50.09 / 54, places=6)
        self.assertAlmostEqual(detail["prezzo_massimo"], 0.96, places=6)


class InvoicesTest(unittest.TestCase):
    def test_invoice_rows_signed_and_totals_per_unit(self):
        rows = cr.invoice_rows(TANQUERAY_2026, conversions(TANQUERAY_2026))
        self.assertEqual([r["numero_documento"] for r in rows], ["29039", "146", "138", "6399"])
        reso = rows[1]
        self.assertTrue(reso["is_reso"])
        self.assertEqual(reso["tipo_documento"], "TD04")
        self.assertEqual(reso["quantita"], -374.0)
        self.assertLess(reso["spesa_totale"], 0)
        totals = cr.invoice_totals(rows)
        self.assertEqual([(t["unita"], t["quantita"]) for t in totals], [("BT", -357.0)])

    def test_invoice_totals_never_mix_units(self):
        rows = cr.invoice_rows(SACCHI_2026, conversions(SACCHI_2026))
        text = cr.quantities_text(cr.invoice_totals(rows))
        self.assertEqual(text, "8 CT + 30 KG (non convertito) + 2 PZ (non convertito)")  # era "211,0 unità"
        self.assertEqual({r["unita_misura"] for r in rows}, {"CT", "CNF", "KG", "PZ"})

    def test_mini_panino_line_uses_invoiced_price(self):
        # Riga 5608: 2 CT x 26,89 = 53,78 (prima 2 x 0,27 = 0,54 dal prezzo sovrascritto).
        row = line(MINI_PANINO, 9, "PPANVE", "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO", "CT", "2",
                   "26.8926", "0.01")
        invoice = cr.invoice_rows([row], conversions([row]))[0]
        self.assertAlmostEqual(invoice["spesa_totale"], 53.78, places=2)
        self.assertAlmostEqual(invoice["prezzo_unitario"], 26.89, places=2)

    def test_pdf_title_and_rendering(self):
        title = cr.report_title([MINI_PANINO.sku_interno],
                                [line(MINI_PANINO, 9, "PPANVE", "PANINO EDNA PARTY BURGER MIX", "CT", "1", "26")])
        self.assertEqual(title, "SG3-52506F3CBE1143E1 - MINI PANINO EDNA BURGHER")
        many = cr.report_title(["A", "B", "C", "D"], [])
        self.assertEqual(many, "Consolidato di 4 articoli (A, B, C...)")
        from app.services.pdf_generator import generate_consumption_invoices_pdf
        rows = TANQUERAY_2026 + [line(SACCHI, 6, "X", "SACCHI & BUSTE <AMBRA>", "KG", "1", "2")]
        pdf = generate_consumption_invoices_pdf("SACCHI & BUSTE", cr.invoice_rows(rows, conversions(rows)), "Nessuno")
        self.assertTrue(pdf.startswith(b"%PDF"))


class TopProductsTest(unittest.TestCase):
    def test_total_spend_does_not_depend_on_limit(self):
        rows = TANQUERAY_2026 + OLIO_2026 + CALYPSO_2026 + SACCHI_2026
        items = cr.aggregate_by_sku(rows, conversions(rows))
        expected = sum(float(r.importo_netto) for r in rows)
        for sort_by in cr.SORT_KEYS:
            top = cr.top_products(items, sort_by, 2)
            self.assertEqual(len(top["prodotti"]), 2)
            self.assertEqual(top["numero_prodotti"], 4)
            self.assertAlmostEqual(top["totale_spesa"], expected, places=2)

    def test_invoices_are_counted_not_lines(self):
        # Due righe nella stessa fattura (come CUBEROLL 1/9600) contano una fattura.
        rows = [line(OLIO, 9, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT", "20", "1.8", fattura=77),
                line(OLIO, 9, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT", "40", "1.8", fattura=77),
                line(OLIO, 9, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT", "20", "1.8", fattura=78)]
        self.assertEqual(by_sku(rows)[OLIO.sku_interno]["numero_fatture"], 2)

    def test_sort_by_invoices_and_quantity(self):
        rows = TANQUERAY_2026 + OLIO_2026 + CALYPSO_2026
        items = cr.aggregate_by_sku(rows, conversions(rows))
        self.assertEqual([p["sku_interno"] for p in cr.top_products(items, "quantita", None)["prodotti"]],
                         [OLIO.sku_interno, CALYPSO.sku_interno, TANQUERAY.sku_interno])
        self.assertEqual(cr.top_products(items, "acquisti", 1)["prodotti"][0]["sku_interno"], CALYPSO.sku_interno)


class FormatTest(unittest.TestCase):
    def test_italian_numbers(self):
        self.assertEqual(cr.format_quantity(Decimal("5940")), "5.940")
        self.assertEqual(cr.format_quantity(-357), "-357")
        self.assertEqual(cr.format_quantity(Decimal("12.5")), "12,5")
        self.assertEqual(cr.format_quantity(Decimal("1234567.891")), "1.234.567,89")

    def test_parse_filters(self):
        self.assertEqual(cr.parse_ids("1, 2"), [1, 2])
        self.assertIsNone(cr.parse_ids("x"))
        self.assertIsNone(cr.parse_ids(object()))
        self.assertEqual(cr.parse_skus("A, B,,A"), ["A", "B"])
        f = cr.ReportFilters.build(location_ids="3", date_from="2026-01-01", skus=["A"])
        self.assertEqual((f.location_ids, f.date_from, f.skus), ((3,), None, ("A",)))


class QueryAndEndpointsTest(unittest.TestCase):
    """Schermo ed Excel usano la stessa funzione; esclusioni e tenant vengono dalla base comune."""

    user = SimpleNamespace(id=1, tenant_id=1)

    def test_query_uses_common_rules(self):
        filters = cr.ReportFilters.build(location_ids="3", fornitore_ids=[22], date_from=date(2026, 1, 1),
                                         skus=["SG3-47E8AE1C5B82B9CB"])
        text = str(cr.lines_select(self.user, filters).compile(dialect=postgresql.dialect(),
                                                               compile_kwargs={"literal_binds": True}))
        self.assertIn("skus_esclusi", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("fatture.tenant_id = 1 OR fatture.tenant_id IS NULL", text)
        self.assertIn("'TD04', 'TD08'", text)
        self.assertIn("LEFT OUTER JOIN location", text)
        self.assertIn("fatture.data_documento >= '2026-01-01'", text)
        self.assertNotIn("prezzo_netto_normalizzato", text)

    def run_endpoints(self, rows):
        from app.api.v1 import intelligence

        async def go():
            with patch.object(cr, "load_lines", AsyncMock(return_value=(rows, conversions(rows)))):
                screen = await intelligence.get_product_consumption(
                    location_ids=None, fornitore_id=None, data_da=None, data_a=None, _admin=self.user, db=None)
                response = await intelligence.export_product_consumption_excel(
                    location_ids=None, fornitore_id=None, data_da=None, data_a=None, _admin=self.user, db=None)
                body = b"".join([chunk async for chunk in response.body_iterator])
                top = await intelligence.get_top_purchased_products(
                    limit=1, sort_by="spesa", fornitore_id=None, fornitore_ids=None, location_ids=None,
                    data_da=None, data_a=None, _admin=self.user, db=None)
            return screen, body, top

        return asyncio.run(go())

    def test_excel_rows_equal_screen_rows(self):
        import io

        import openpyxl
        rows = TANQUERAY_2026 + OLIO_2026 + SACCHI_2026
        screen, body, top = self.run_endpoints(rows)
        sheet = openpyxl.load_workbook(io.BytesIO(body)).active
        values = [list(r) for r in sheet.iter_rows(min_row=2, values_only=True)]
        data, total = values[:-1], values[-1]
        self.assertEqual([r[0] for r in data], [i["sku_interno"] for i in screen])
        self.assertEqual([round(r[9], 2) for r in data], [round(i["spesa_totale"], 2) for i in screen])
        self.assertAlmostEqual(total[9], sum(i["spesa_totale"] for i in screen), places=2)
        sacchi = next(r for r in data if r[0] == SACCHI.sku_interno)
        self.assertEqual(sacchi[4], "unità diverse")
        self.assertEqual(sacchi[8], "n.d.")
        self.assertEqual(top["numero_prodotti"], len(screen))
        self.assertAlmostEqual(top["totale_spesa"], sum(i["spesa_totale"] for i in screen), places=2)

    def test_excluded_sku_is_refused_also_in_a_multiple_selection(self):
        from app.api.v1 import intelligence

        class DB:
            async def scalars(self, stmt):
                return SimpleNamespace(all=lambda: ["SKU-ESCLUSO"])

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(intelligence._selected_skus(DB(), "SKU-OK,SKU-ESCLUSO"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_selection_of_all_1757_skus_goes_in_the_body(self):
        from app.api.v1.intelligence import ConsumptionSelection, router
        selection = ConsumptionSelection(skus=[f"SG3-{i:016X}" for i in range(1757)], location_ids=[1])
        self.assertEqual(len(selection.skus), 1757)
        posts = {r.path for r in router.routes if "POST" in getattr(r, "methods", set())}
        for path in ("/product-consumption/detail", "/product-consumption/invoices",
                     "/product-consumption/invoices-pdf"):
            self.assertIn(path, posts)


if __name__ == "__main__":
    unittest.main()
