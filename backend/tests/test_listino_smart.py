"""Listino Smart (PR7, rapporto schermate 14/11/2026: A8, A9, A10, M16, M17, M18, B7, B8).

Casi reali dell'export di produzione del 14/11/2026, nessun database:
- TOVAGLIETTA CARTAPAGLIA: consigliato VE.MO 7,45 (13,86 / fattore 1,86), non MELIUS 3,90;
- Candeggina candidalba 4L: consigliato KITO 1,50 (6,00 al cartone da 4), non VE.MO 2,01;
- Coltello betulla: consigliato KITO 1,60, non VE.MO 1,19 (confezione da 50 = 2,38);
- PEPITA BIANCA: spot = ultimo prezzo 17,495, non il minimo di marzo 5,256;
- foglio prezzi: Red Bull 19,672 CT -> 19,672 Pz bloccato, il precaricato non scrive nulla.

PYTHONPATH=. python -m unittest discover -s tests -p 'test_listino_smart.py' -v   (da backend/)
"""
import asyncio
import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import smart_price_sheet as sps  # noqa: E402
from app.services.purchase_recommendation import (  # noqa: E402
    comparable_listino_price,
    rank_offers_keeping_incomparable,
)
from app.services.smart_price_spot import SpotLine, compute_spot_offers, spot_lines_query  # noqa: E402

TODAY = date(2026, 11, 15)
VEMO, MELIUS, ALFA, KITO, EUROCARTA, NAVAS = 21, 9, 3, 24, 6, 5
REPO = Path(__file__).resolve().parents[2]


def product(pid, sku, name, unit="Pz", unit_count=1, category="Materiali"):
    return Product(id=pid, sku_interno=sku, canonical_name=name, normalized_name=name.lower(),
                   comparison_unit=unit, unit_count=unit_count, category=category, is_active=True)


def alias(aid, supplier, pid, code, description, pack=None, fattore=None, volume_ml=None, weight_g=None):
    return SupplierProductAlias(
        id=aid, supplier_id=supplier, product_id=pid, supplier_code=code, raw_description=description,
        status="approved", source="manual", pack_qty=pack,
        fattore_confezione=Decimal(fattore) if fattore else None, volume_ml=volume_ml, weight_g=weight_g,
    )


def line(rid, sku, supplier, location, day, code, description, unit, price, discount="0"):
    return SpotLine(rid, sku, supplier, location, day, code, description, unit, Decimal(price), Decimal(discount))


def ranked(offers):
    result = rank_offers_keeping_incomparable([dict(o) for o in offers.values()])
    return result["recommended_offer"]["supplier_id"] if result["recommended_offer"] else None, result


TOVAGLIETTA = product(2738, "CAN-3-12868-1794582617", "TOVAGLIETTA CARTAPAGLIA 30X40 500PZ")
TOVAGLIETTA_ALIASES = [
    alias(3539, VEMO, 2738, "DELCP1030", "Carta paglia cm 30x40 10kg 90gr (930 pezzi circa) 62968",
          fattore="1.8600", weight_g=10000),
    alias(4309, MELIUS, 2738, "PBUSNE", "CARTA PAGLIA 30X40 CF 250 PZ", fattore="0.5000"),
    alias(5079, ALFA, 2738, "ALM11109", "TOVAGLIETTA CARTAPAGLIA 30X40 500PZ"),
]
_CP = "Carta paglia cm 30x40 10kg 90gr (930 pezzi circa) 62968"
TOVAGLIETTA_LINES = [
    line(6768, TOVAGLIETTA.sku_interno, VEMO, 1, date(2026, 3, 28), "DELCP1030", _CP, "CF", "13.8600"),
    line(16417, TOVAGLIETTA.sku_interno, VEMO, 5, date(2026, 5, 28), "DELCP1030", _CP, "CF", "14.5600"),
    line(16557, TOVAGLIETTA.sku_interno, VEMO, 5, date(2026, 7, 1), "DELCP1030", _CP, "CF", "14.5600"),
    line(16792, TOVAGLIETTA.sku_interno, VEMO, 5, date(2026, 9, 16), "DELCP1030", _CP, "CF", "14.5600"),
    line(10451, TOVAGLIETTA.sku_interno, MELIUS, 1, date(2026, 8, 31), "PBUSNE", "CARTA PAGLIA 30X40 CF 250 PZ", "CF", "3.9000"),
    line(12868, TOVAGLIETTA.sku_interno, ALFA, 1, date(2026, 9, 1), "ALM11109", "TOVAGLIETTA CARTAPAGLIA 30X40 500PZ", "CF", "8.7000"),
]

CANDEGGINA = product(1132, "CAN-21-6177-1794491393", "Candeggina candidalba 4 litri")
CANDEGGINA_ALIASES = [
    alias(2963, VEMO, 1132, "ALBCCA", "Candeggina candidalba 4 litri"),
    alias(4616, KITO, 1132, None, "CANDIDALBA CANDEGGINA ML 4000 CT DA 4 TANICHE", pack=4, volume_ml=4000),
]
CANDEGGINA_LINES = [
    line(6475, CANDEGGINA.sku_interno, VEMO, 1, date(2026, 1, 9), "ALBCCA", "Candeggina candidalba 4 litri", "TA", "2.0100"),
    line(6640, CANDEGGINA.sku_interno, VEMO, 1, date(2026, 7, 15), "ALBCCA", "Candeggina candidalba 4 litri", "TA", "2.1000"),
    line(16499, CANDEGGINA.sku_interno, VEMO, 5, date(2026, 6, 17), "ALBCCA", "Candeggina candidalba 4 litri", "TA", "2.1000"),
    line(11682, CANDEGGINA.sku_interno, KITO, 1, date(2026, 8, 31), None,
         "CANDIDALBA CANDEGGINA ML 4000 CT DA 4 TANICHE", "CT", "6.0000"),
]

COLTELLO = product(2468, "CAN-24-11554-1794579549", "COLTELLO IN LEGNO DI BETULLA 16CM 100PZXCF")
_KC = "COLTELLO IN LEGNO DI BETULLA 16CM 100PZXCF"
_VC = "Coltelli in betulla 16cm 50 pezzi biodegradabile e compostabile 0128"
COLTELLO_ALIASES = [
    alias(4617, KITO, 2468, None, _KC),
    alias(4935, EUROCARTA, 2468, "00965", "IMBALL.COLTELLO LEGNO 100PZ"),
    alias(6253, VEMO, 2468, "ICOCB50", _VC, fattore="0.5000"),
]
COLTELLO_LINES = [
    line(11554, COLTELLO.sku_interno, KITO, 1, date(2026, 6, 8), None, _KC, "CNF", "1.6000"),
    line(11589, COLTELLO.sku_interno, KITO, 1, date(2026, 6, 23), None, _KC, "CNF", "1.6000"),
    line(11566, COLTELLO.sku_interno, KITO, 1, date(2026, 7, 2), None, _KC, "CNF", "1.6000"),
    line(12525, COLTELLO.sku_interno, EUROCARTA, 1, date(2026, 7, 13), "00965", "IMBALL.COLTELLO LEGNO 100PZ", "PZ", "1.7000"),
    line(12570, COLTELLO.sku_interno, EUROCARTA, 1, date(2026, 8, 8), "00965", "IMBALL.COLTELLO LEGNO 100PZ", "PZ", "1.8000"),
    line(12619, COLTELLO.sku_interno, EUROCARTA, 1, date(2026, 9, 15), "00965", "IMBALL.COLTELLO LEGNO 100PZ", "PZ", "2.1311", "0.0516"),
    line(16695, COLTELLO.sku_interno, VEMO, 5, date(2026, 7, 30), "ICOCB50", _VC, "CF", "1.1900"),
]


# A8 - spot convertito e consigliato
class SpotConvertedTest(unittest.TestCase):
    def spot(self, prod, lines, aliases):
        return compute_spot_offers(lines, {prod.sku_interno: prod}, aliases, TODAY)

    def test_tovaglietta_recommends_vemo_745(self):
        offers = {k[1]: v for k, v in self.spot(TOVAGLIETTA, TOVAGLIETTA_LINES, TOVAGLIETTA_ALIASES).items()}
        self.assertEqual(offers[VEMO]["unit_price_normalized"], "7.4516")   # 13,86 / 1,86
        self.assertEqual(offers[MELIUS]["unit_price_normalized"], "7.8000")  # 3,90 / 0,5
        self.assertEqual(offers[ALFA]["unit_price_normalized"], "8.7000")
        # La cella mostra il prezzo fatturato nella sua unità.
        self.assertEqual((offers[MELIUS]["price"], offers[MELIUS]["uom"]), ("3.9000", "CF"))
        recommended, _ = ranked(offers)
        self.assertEqual(recommended, VEMO)
        # Ultimo prezzo della sede 1 (28/03): più di 120 giorni, segnato come vecchio.
        self.assertEqual(offers[VEMO]["invoice_date"], "2026-03-28")
        self.assertTrue(offers[VEMO]["stale"])
        self.assertFalse(offers[MELIUS]["stale"])

    def test_candeggina_recommends_kito_150(self):
        offers = {k[1]: v for k, v in self.spot(CANDEGGINA, CANDEGGINA_LINES, CANDEGGINA_ALIASES).items()}
        self.assertEqual(offers[KITO]["unit_price_normalized"], "1.5000")  # 6,00 / 4 taniche
        self.assertEqual(offers[VEMO]["unit_price_normalized"], "2.1000")  # ultimo, non il minimo 2,01
        self.assertEqual(ranked(offers)[0], KITO)

    def test_coltello_recommends_kito_160(self):
        offers = {k[1]: v for k, v in self.spot(COLTELLO, COLTELLO_LINES, COLTELLO_ALIASES).items()}
        self.assertEqual(offers[KITO]["unit_price_normalized"], "1.6000")
        self.assertEqual(offers[VEMO]["unit_price_normalized"], "2.3800")  # 1,19 per 50 pezzi
        self.assertEqual(offers[EUROCARTA]["unit_price_normalized"], "2.1300")
        self.assertEqual(ranked(offers)[0], KITO)

    def test_old_raw_minimum_would_pick_wrong_suppliers(self):
        # Il codice precedente metteva in classifica il prezzo per unità di fattura.
        def raw_min(lines):
            best = {}
            for item in lines:
                best[item.fornitore_id] = min(best.get(item.fornitore_id, item.net), item.net)
            return min(best, key=lambda supplier: (best[supplier], supplier))
        self.assertEqual(raw_min(TOVAGLIETTA_LINES), MELIUS)
        self.assertEqual(raw_min(CANDEGGINA_LINES), VEMO)
        self.assertEqual(raw_min(COLTELLO_LINES), VEMO)

    def test_unreliable_conversion_stays_in_invoice_unit_out_of_ranking(self):
        sacchetti = product(77, "SACCHETTI-KRAFT", "SACCHETTI CARTA KRAFT BIANCO 14X28 10KG DL")
        lines = [
            line(1, "SACCHETTI-KRAFT", VEMO, 1, date(2026, 5, 28), "SAC1", "Sacchetti kraft 14x28", "KG", "2.1600"),
            line(2, "SACCHETTI-KRAFT", KITO, 1, date(2026, 6, 1), None, "SACCHETTI KRAFT 14X28", "CT", "22.5000"),
        ]
        offers = {k[1]: v for k, v in self.spot(sacchetti, lines, []).items()}
        self.assertIsNone(offers[VEMO]["unit_price_normalized"])
        self.assertFalse(offers[VEMO]["comparison_reliable"])
        self.assertEqual((offers[VEMO]["price"], offers[VEMO]["uom"]), ("2.1600", "KG"))
        recommended, result = ranked(offers)
        self.assertEqual(recommended, KITO)
        vemo = next(o for o in result["offers"] if o["supplier_id"] == VEMO)
        self.assertFalse(vemo["is_recommended"])

    def test_ambiguous_links_make_conversion_uncertain(self):
        voce = product(78, "AMB", "Tovaglioli 33x33")
        aliases = [alias(1, VEMO, 78, "T1", "Tovaglioli 33x33 conf 50", fattore="0.5"),
                   alias(2, VEMO, 78, "T2", "Tovaglioli 33x33 conf 100")]
        lines = [line(1, "AMB", VEMO, 1, date(2026, 9, 1), "T9", "Tovaglioli nuovi", "CF", "3.0000")]
        offer = self.spot(voce, lines, aliases)[("AMB", VEMO)]
        self.assertIsNone(offer["unit_price_normalized"])


# M17 - spot = ultimo prezzo per sede, non il minimo di sempre; righe anomale escluse
class SpotLatestPriceTest(unittest.TestCase):
    def test_pepita_bianca_uses_last_price(self):
        pepita = product(2186, "CAN-9-7320-1794578286", "CIOCCOLATO PEPITA BIANCA IRCA", unit="Kg", category="Food")
        lines = [
            line(7650, pepita.sku_interno, MELIUS, 1, date(2026, 3, 18), "IESSA15", "CIOCCOLATO PEPITA BIANCA IRCA", "KG", "5.2563", "0.0057"),
            line(11282, pepita.sku_interno, MELIUS, 1, date(2026, 10, 16), "IESSA15", "CIOCCOLATO PEPITA BIANCA", "KG", "17.5000"),
            line(11318, pepita.sku_interno, MELIUS, 1, date(2026, 10, 21), "IESSA15", "CIOCCOLATO PEPITA BIANCA", "KG", "17.4960", "0.0057"),
        ]
        offer = compute_spot_offers(lines, {pepita.sku_interno: pepita}, [], TODAY)[(pepita.sku_interno, MELIUS)]
        self.assertEqual(offer["unit_price_normalized"], "17.4950")
        self.assertEqual(offer["invoice_date"], "2026-10-21")
        self.assertFalse(offer["stale"])

    def test_one_cent_line_is_ignored(self):
        burger = product(5, "BURGER", "HAMBURGER SCOTTONA BURGERPIU' 180G", unit="Kg", category="Food")
        lines = [
            line(1, "BURGER", MELIUS, 1, date(2026, 7, 1), "HB", "HAMBURGER", "KG", "12.5000"),
            line(2, "BURGER", MELIUS, 1, date(2026, 8, 1), "HB", "HAMBURGER", "KG", "12.9000"),
            line(8457, "BURGER", MELIUS, 1, date(2026, 9, 1), "HB", "HAMBURGER", "KG", "0.0100"),
        ]
        offer = compute_spot_offers(lines, {"BURGER": burger}, [], TODAY)[("BURGER", MELIUS)]
        self.assertEqual(offer["unit_price_normalized"], "12.9000")

    def test_query_uses_shared_purchase_lines_rules(self):
        sql = str(spot_lines_query(None, skus=["A"], supplier_ids=[1], location_id=5).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("NOT IN ('TD04', 'TD08')", sql)        # note di credito fuori (B7)
        self.assertIn("skus_esclusi", sql)
        self.assertIn("righe_escluse_statistiche", sql)
        self.assertIn("is_omaggio", sql)
        self.assertIn("location_id IN (5)", sql)
        self.assertNotIn("prezzo_netto_normalizzato", sql)


# A10 / M16 - listino senza unità non confrontabile, a cartone convertito
class ListinoComparisonTest(unittest.TestCase):
    def test_listino_without_unit_is_not_comparable(self):
        retina = product(90, "RETINA", "RETINA 60G")
        eurocarta = SimpleNamespace(prezzo_pattuito=Decimal("0.50"), unita_misura=None)
        vemo = SimpleNamespace(prezzo_pattuito=Decimal("9.62"), unita_misura="CF")
        self.assertIsNone(comparable_listino_price(eurocarta, retina))
        offers = {
            EUROCARTA: {"supplier_id": EUROCARTA, "unit_price_normalized": None, "price": "0.5000", "source_type": "contratto", "uom": None},
            VEMO: {"supplier_id": VEMO, "unit_price_normalized": f"{comparable_listino_price(vemo, retina):.4f}", "price": "9.6200", "source_type": "contratto", "uom": "CF"},
        }
        recommended, result = ranked(offers)
        self.assertEqual(recommended, VEMO)
        eu = next(o for o in result["offers"] if o["supplier_id"] == EUROCARTA)
        self.assertFalse(eu["is_recommended"])
        self.assertIsNone(eu["unit_price_normalized"])

    def test_red_bull_box_price_is_ranked_per_can(self):
        red_bull = product(10, "RB", "RED BULL 0,25 X24 LATT", unit_count=24, category="Beverage")
        navas = SimpleNamespace(prezzo_pattuito=Decimal("19.672"), unita_misura="CT")
        self.assertEqual(f"{comparable_listino_price(navas, red_bull):.4f}", "0.8197")


# A9 - foglio prezzi: niente cambio di unità senza conversione
class PriceChangeClassificationTest(unittest.TestCase):
    def test_family_change_with_same_price_is_blocked(self):
        # RED BULL Navas 19,672 CT -> 19,672 Pz: 24 volte il prezzo a lattina.
        self.assertEqual(sps.classify_price_change(Decimal("19.672"), "CT", Decimal("19.672"), "Pz"),
                         ("error", "uom_change_without_price_change"))
        # Calypso VE.MO 50,09 CF -> 50,09 Pz.
        self.assertEqual(sps.classify_price_change(Decimal("50.09"), "CF", Decimal("50.09"), "Pz")[0], "error")

    def test_same_family_is_unchanged(self):
        self.assertEqual(sps.classify_price_change(Decimal("0.82"), "PZ", Decimal("0.82"), "Pz"), ("unchanged", None))
        self.assertEqual(sps.classify_price_change(Decimal("4.50"), "CF", Decimal("4.50"), "CT"), ("unchanged", None))

    def test_unit_assignment_needs_explicit_confirmation(self):
        self.assertEqual(sps.classify_price_change(Decimal("0.50"), None, Decimal("0.50"), "Pz"),
                         ("unchanged", "unit_assignment"))
        self.assertEqual(sps.classify_price_change(Decimal("0.50"), "", Decimal("0.50"), "Pz", allow_unit_assignment=True),
                         ("update", None))

    def test_new_price_and_new_listino(self):
        self.assertEqual(sps.classify_price_change(Decimal("19.672"), "CT", Decimal("0.85"), "Pz"), ("update", None))
        self.assertEqual(sps.classify_price_change(None, None, Decimal("5.68"), "Kg"), ("create", None))

    def test_sheet_header_is_recognised(self):
        parsed = sps.parse_clipboard_table(
            "Nome informale / rapido ordine (facoltativo)\tProdotto reale\tUnità di misura\tNavas\n"
            "\tRED BULL 0,25 X24 LATT\tPz\t0,85"
        )
        self.assertEqual(parsed["supplier_headers"], ["Navas"])
        self.assertEqual(parsed["rows"][0]["product_ref"], "RED BULL 0,25 X24 LATT")
        self.assertEqual(parsed["rows"][0]["uom"], "Pz")


class PreloadedSheetPreviewTest(unittest.TestCase):
    """Anteprima e conferma con il servizio vero e un database finto."""

    RED_BULL = product(10, "RB", "RED BULL 0,25 X24 LATT", unit_count=24, category="Beverage")
    NAVAS = SimpleNamespace(id=NAVAS, nome_azienda="Navas Distribuzione", partita_iva="01234567890",
                            archived_at=None, attivo_whitelist=True)

    def preview(self, text, listino_unit, listino_price="19.6720"):
        current = SimpleNamespace(id=500, sku_interno="RB", fornitore_id=NAVAS, prezzo_pattuito=Decimal(listino_price),
                                  unita_misura=listino_unit, data_inizio_validita=date(2026, 1, 1), data_scadenza=None)

        def result(rows):
            res = MagicMock()
            res.all.return_value = rows
            return res

        db = MagicMock()
        db.scalars = AsyncMock(side_effect=[result([self.NAVAS]), result([self.RED_BULL]), result([]),
                                            result([]), result([current])])
        db.scalar = AsyncMock(return_value=None)
        db.flush = AsyncMock()
        scope = MagicMock()
        scope.eligible_supplier_ids.side_effect = lambda **kwargs: kwargs["supplier_ids"]
        with patch.object(sps, "load_supplier_catalog_scope", AsyncMock(return_value=scope)):
            return asyncio.run(sps.build_price_preview(
                db, text_value=text, supplier_mapping={}, product_mapping={}, effective_date=TODAY,
                default_uom="Pz", create_missing_products=False, location_id=None, actor_id=1,
            ))

    HEADER = "Nome informale / rapido ordine (facoltativo)\tProdotto reale\tUnità di misura\tNavas Distribuzione\n"

    def test_red_bull_box_to_piece_is_blocked(self):
        preview = self.preview(self.HEADER + "\tRED BULL 0,25 X24 LATT\tPz\t19,672", "CT")
        payload = preview.preview_payload
        self.assertFalse(payload["can_commit"])
        self.assertEqual([e["type"] for e in payload["errors"]], ["uom_change_without_price_change"])
        self.assertEqual(payload["changes"], [])

    def test_preloaded_sheet_confirmed_without_changes_writes_nothing(self):
        # Listino PZ precaricato in una colonna C "Pz": stesso prezzo, stessa famiglia.
        preview = self.preview(self.HEADER + "\tRED BULL 0,25 X24 LATT\tPz\t0,8197", "PZ", listino_price="0.8197")
        payload = preview.preview_payload
        self.assertEqual(payload["counts"], {"create": 0, "update": 0, "unchanged": 1, "errors": 0})
        self.assertTrue(payload["can_commit"])

        db = MagicMock()
        db.scalar = AsyncMock(return_value=preview)
        db.get = AsyncMock(return_value=self.NAVAS)
        db.flush = AsyncMock()
        preview.status = "ready"
        preview.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        _, outcome = asyncio.run(sps.commit_price_preview(db, token=preview.id, actor_id=1))
        self.assertEqual((outcome["created"], outcome["updated"], outcome["unchanged"]), (0, 0, 1))
        db.add.assert_not_called()

    def test_listino_without_unit_is_not_silently_assigned(self):
        preview = self.preview(self.HEADER + "\tRED BULL 0,25 X24 LATT\tPz\t19,672", None)
        payload = preview.preview_payload
        self.assertEqual(payload["changes"][0]["action"], "unchanged")
        self.assertEqual([w["type"] for w in payload["warnings"]], ["unit_assignment"])


# Frontend (nessun runner TS in CI): controlli sul sorgente della schermata.
class SmartPriceSheetFrontendSourceTest(unittest.TestCase):
    source = (REPO / "frontend" / "src" / "components" / "SmartPriceSheet.tsx").read_text(encoding="utf-8")

    def test_matrix_pages_by_100(self):
        self.assertIn("const MATRIX_PAGE_SIZE = 100", self.source)
        self.assertIn("limit: String(MATRIX_PAGE_SIZE)", self.source)
        self.assertIn("offset + MATRIX_PAGE_SIZE", self.source)
        self.assertNotRegex(self.source, r"offset [-+] 50")

    def test_sheet_preloads_only_listini_in_column_c_unit_and_sends_changes(self):
        self.assertIn("offer.source_type === 'contratto' && family && family === unitFamily(columnC)", self.source)
        self.assertIn("text: sheetChanges.text", self.source)
        self.assertNotRegex(self.source, r"JSON\.stringify\(\{\s*text: sheetText\(sheet\)")

    def test_all_categories_and_pages_are_loaded(self):
        self.assertIn("id: 'Attrezzatura'", self.source)
        self.assertIn("id: 'Gelati confezionati'", self.source)
        self.assertIn("while (rows.length < first.total)", self.source)

    def test_cell_shows_unit_converted_price_and_incomparable_badge(self):
        self.assertIn("offer.uom ? ` / ${offer.uom}` : ''", self.source)
        self.assertIn("unità mancante", self.source)
        self.assertIn("conversione incerta", self.source)
        self.assertTrue(re.search(r"vecchio", self.source))

    def test_cross_supplier_matrix_removed(self):
        self.assertFalse((REPO / "frontend" / "src" / "components" / "CrossSupplierMatrix.tsx").exists())
        intelligence = (REPO / "backend" / "app" / "api" / "v1" / "intelligence.py").read_text(encoding="utf-8")
        for path in ('"/cross-supplier"', '"/cross-location"', '"/export-vendor-passport'):
            self.assertNotIn(path, intelligence)


if __name__ == "__main__":
    unittest.main()
