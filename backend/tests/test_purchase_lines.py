"""Base comune delle righe d'acquisto (services/purchase_lines.py).

I casi riproducono righe reali di produzione (export del 14/11/2026): Tanqueray
reso Navas, MINI PANINO a cartone da 100, olio girasole MELIUS in latte da 5 e
20 L, buste ambra a cartone/kg, Calypso a confezione da 54. Nessun database.
"""
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.fatture import TipoDocumento  # noqa: E402
from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import purchase_lines as pl  # noqa: E402
from app.services.matching import normalize_price_for_comparison  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402


def sql(statement, literal=False) -> str:
    kwargs = {"compile_kwargs": {"literal_binds": True}} if literal else {}
    return str(statement.compile(dialect=postgresql.dialect(), **kwargs))


def product(pid, sku, unit, unit_count=1, volume_ml=None, weight_g=None, name="voce"):
    return Product(id=pid, sku_interno=sku, canonical_name=name, comparison_unit=unit,
                   unit_count=unit_count, volume_ml=volume_ml, weight_g=weight_g)


def alias(aid, supplier, pid, code, description, pack=None, volume_ml=None, weight_g=None,
          status="approved", fattore=None):
    return SupplierProductAlias(
        id=aid, supplier_id=supplier, product_id=pid, supplier_code=code, raw_description=description,
        normalized_description=normalize_text(description), pack_qty=pack, volume_ml=volume_ml,
        weight_g=weight_g, status=status, fattore_confezione=fattore, source="manual",
    )


# ── Dati reali ──
MINI_PANINO = product(1, "SG3-52506F3CBE1143E1", "Pz", unit_count=1, name="MINI PANINO EDNA BURGHER")
MINI_PANINO_DESC = "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO"
MINI_PANINO_ALIAS = alias(2558, 9, 1, "PPANVE", MINI_PANINO_DESC, pack=100)

OLIO = product(58, "SG3-55FE5E10318B7F06", "Lt", unit_count=1, name="OLIO GIRASOLE")
OLIO_5 = alias(2522, 9, 58, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", volume_ml=5000)
OLIO_20 = alias(2600, 9, 58, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", volume_ml=20000)

TANQUERAY = product(276, "SG3-47E8AE1C5B82B9CB", "Pz", unit_count=1, name="GIN TANQUERAY 100 CL")
TANQUERAY_ALIAS = alias(2243, 22, 276, "GIN0001", "GIN TANQUERAY 100 CL", volume_ml=1000)

BUSTE = product(700, "SG3-165D17EA2619C309", "CT", unit_count=1, name="BUSTE AMBRA 90X120")
BUSTE_DESC = "Buste ambra N.U. PE/LD cm 90x120h 18kg"

CALYPSO = product(645, "CAN-21-31-1793543247", "Pz", unit_count=1, name="Calypso calice fluttino")
CALYPSO_CF = alias(2000, 21, 645, "BORBF54", "Calypso calice fluttino bicchiere 113ml 54 pezzi", pack=54, volume_ml=113)
CALYPSO_PZ = alias(2245, 21, 645, "BORCF", "Calypso calice fluttino bicchiere 113ml", pack=54, volume_ml=113)

ALIASES = pl.AliasIndex([MINI_PANINO_ALIAS, OLIO_5, OLIO_20, TANQUERAY_ALIAS, CALYPSO_CF, CALYPSO_PZ])
PRODUCTS = {p.id: p for p in (MINI_PANINO, OLIO, TANQUERAY, BUSTE, CALYPSO)}


def row(fornitore, prod, code, description, uom, qty, price, discount="0", tipo="TD01", omaggio=False):
    return SimpleNamespace(
        fornitore_id=fornitore, product_id=prod.id if prod else None, codice_fornitore=code,
        descrizione=description, unita_misura=uom, quantita=Decimal(qty), prezzo_unitario=Decimal(price),
        sconto_percentuale=Decimal(discount), tipo_documento=tipo, is_omaggio=omaggio,
    )


class DocumentSignTest(unittest.TestCase):
    def test_credit_notes_are_negative(self):
        self.assertEqual(pl.document_sign("TD04"), -1)
        self.assertEqual(pl.document_sign(TipoDocumento.TD04), -1)
        self.assertEqual(pl.document_sign("TD08"), -1)  # nota di credito semplificata
        self.assertEqual(pl.document_sign(TipoDocumento.TD08), -1)

    def test_invoices_are_positive(self):
        for tipo in ("TD01", "TD24", "TD25", TipoDocumento.TD24, None, ""):
            self.assertEqual(pl.document_sign(tipo), 1, tipo)

    def test_sql_sign_lists_td04_and_td08(self):
        text = sql(select(pl.sign_sql()), literal=True)
        self.assertIn("'TD04'", text)
        self.assertIn("'TD08'", text)
        self.assertIn("ELSE 1", text)


class NetAmountTest(unittest.TestCase):
    def test_net_unit_price_uses_invoiced_price_and_discount(self):
        # MINI PANINO 07/09/2026: 26,8926 con sconto 0,01% = 26,89 a cartone (non 0,2689).
        self.assertEqual(pl.line_net_unit_price("26.8926", "0.01").quantize(Decimal("0.01")), Decimal("26.89"))
        self.assertEqual(pl.line_net_unit_price("10", None), Decimal("10"))

    def test_credit_note_amount_is_negative(self):
        self.assertEqual(pl.line_net_amount("15.16", "0", "1", "TD04"), Decimal("-15.16"))
        self.assertEqual(pl.line_net_amount("15.16", "0", "1", "TD08"), Decimal("-15.16"))
        self.assertEqual(pl.signed_quantity("3", "TD04"), Decimal("-3"))

    def test_tanqueray_2026_with_navas_return(self):
        # Le 4 righe 2026 di GIN TANQUERAY 100 CL: il reso di maggio copre acquisti 2025.
        lines = [
            row(22, TANQUERAY, "GIN0001", "GIN TANQUERAY 100 CL", "BT", "374", "15.1639", tipo="TD04"),
            row(22, TANQUERAY, "GIN0001", "GIN TANQUERAY 100 CL", "BT", "1", "15.16", tipo="TD04"),
            row(22, TANQUERAY, "GIN0001", "GIN TANQUERAY 100 CL", "BT", "6", "15.1633"),
            row(22, TANQUERAY, "GIN0001", "GIN TANQUERAY 100 CL", "BT", "12", "13.3033"),
        ]
        qty = sum(pl.signed_quantity(r.quantita, r.tipo_documento) for r in lines)
        amount = sum(pl.line_net_amount(r.prezzo_unitario, r.sconto_percentuale, r.quantita, r.tipo_documento)
                     for r in lines)
        self.assertEqual(qty, Decimal("-357"))
        self.assertEqual(amount.quantize(Decimal("0.01")), Decimal("-5435.84"))
        self.assertEqual({pl.normalized_unit(r.unita_misura) for r in lines}, {"BT"})
        # Il reso non entra nelle medie: solo i 2 acquisti pagati.
        in_average = [r for r in lines if pl.counts_for_average(r.is_omaggio, r.prezzo_unitario,
                                                                  r.sconto_percentuale, r.tipo_documento)]
        self.assertEqual(len(in_average), 2)

    def test_sql_amount_never_reads_prezzo_netto_normalizzato(self):
        text = sql(select(pl.signed_amount_sql(), pl.net_unit_price_sql()))
        self.assertIn("prezzo_unitario_fatturato", text)
        self.assertNotIn("prezzo_netto_normalizzato", text)
        self.assertNotIn("prezzo_netto_normalizzato", sql(pl.purchase_lines_select(None)))


class FreeLineTest(unittest.TestCase):
    def test_free_lines(self):
        self.assertTrue(pl.is_free_line(True, "26.89", "0"))
        self.assertTrue(pl.is_free_line(False, "0", "0"))
        self.assertTrue(pl.is_free_line(False, "12", "100"))
        self.assertFalse(pl.is_free_line(False, "12", "10"))

    def test_free_lines_and_credit_notes_stay_out_of_averages(self):
        self.assertFalse(pl.counts_for_average(True, "0", "0", "TD01"))
        self.assertFalse(pl.counts_for_average(False, "10", "0", "TD04"))
        self.assertFalse(pl.counts_for_average(False, "10", "0", "TD08"))
        self.assertTrue(pl.counts_for_average(False, "10", "0", "TD24"))

    def test_sql_average_flag(self):
        text = sql(select(pl.counts_for_average_sql()), literal=True)
        self.assertIn("is_omaggio", text)
        self.assertIn("NOT IN ('TD04', 'TD08')", text)


class NormalizedUnitTest(unittest.TestCase):
    def test_unit_map(self):
        cases = {
            "K.": "KG", "KGM": "KG", "kg": "KG", "Kg.": "KG",
            "N.": "PZ", "NR": "PZ", "nr.": "PZ", "PZ": "PZ", "pz.": "PZ", "Pezzi": "PZ",
            "LT": "LT", "L": "LT", "Ltr": "LT",
            "CT": "CT", "CRT": "CT", "CF": "CNF", "CNF": "CNF", "conf.": "CNF",
            "BT": "BT", "BTL": "BT",
            "": "N.D.", None: "N.D.", "  ": "N.D.", ".": "N.D.",
            "COL": "PZ", "sc": "SC",
        }
        for raw, expected in cases.items():
            self.assertEqual(pl.normalized_unit(raw), expected, raw)

    def test_sql_unit_map_has_the_same_entries(self):
        text = sql(select(pl.normalized_unit_sql()), literal=True)
        self.assertIn("WHEN 'NR' THEN 'PZ'", text)
        self.assertIn("WHEN 'KGM' THEN 'KG'", text)
        self.assertIn("WHEN '' THEN 'N.D.'", text)
        self.assertIn("btrim", text)
        for spelling, label in pl.UNIT_LABELS.items():
            self.assertIn(f"WHEN '{spelling}' THEN '{label}'", text)


class ConversionTest(unittest.TestCase):
    def conv(self, prod, code, description, uom, fornitore=9):
        found = ALIASES.resolve(fornitore, prod.id, code, description)
        return pl.line_conversion(product=prod, alias=found, unita_misura=uom, descrizione=description)

    def test_mini_panino_carton_of_100(self):
        c = self.conv(MINI_PANINO, "PPANVE", MINI_PANINO_DESC, "CT")
        self.assertTrue(c.reliable)
        self.assertEqual(c.factor, Decimal("100"))
        self.assertEqual(c.comparison_unit, "Pz")
        self.assertEqual(c.quantity(Decimal("2")), Decimal("200"))
        self.assertEqual(c.unit_price(pl.line_net_unit_price("25.90")), Decimal("0.259"))

    def test_free_carton_keeps_the_factor(self):
        # Omaggio a prezzo 0: il fattore non dipende dal prezzo (1 CT = 100 pz).
        c = self.conv(MINI_PANINO, "PPANVE", MINI_PANINO_DESC, "CT")
        self.assertEqual(c.quantity(Decimal("1")), Decimal("100"))
        self.assertEqual(c.unit_price(Decimal("0")), Decimal("0"))

    def test_pack_read_from_description_when_unit_count_is_default(self):
        # Nessun alias: unit_count=1 è il default, la confezione si legge da "(CF.100PZ)".
        c = pl.line_conversion(product=MINI_PANINO, alias=None, unita_misura="CT", descrizione=MINI_PANINO_DESC)
        self.assertTrue(c.reliable)
        self.assertEqual(c.factor, Decimal("100"))

    def test_default_unit_count_is_not_a_known_pack(self):
        c = pl.line_conversion(product=MINI_PANINO, alias=None, unita_misura="CT", descrizione="PANINO EDNA GELO")
        self.assertFalse(c.reliable)
        self.assertIsNone(c.factor)
        self.assertIsNone(c.quantity(Decimal("2")))
        self.assertIsNone(c.unit_price(Decimal("26.89")))

    def test_explicit_unit_count_is_a_known_pack(self):
        prod = product(5, "SKU-X", "Pz", unit_count=24)
        c = pl.line_conversion(product=prod, alias=None, unita_misura="CT", descrizione="ACQUA")
        self.assertTrue(c.reliable)
        self.assertEqual(c.factor, Decimal("24"))

    def test_oil_alias_resolved_by_code_5_vs_20_litres(self):
        five = self.conv(OLIO, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", "NR")
        twenty = self.conv(OLIO, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "NR")
        self.assertEqual((five.reliable, five.factor), (True, Decimal("5")))
        self.assertEqual((twenty.reliable, twenty.factor), (True, Decimal("20")))
        self.assertEqual(twenty.comparison_unit, "Lt")

    def test_oil_invoiced_in_litres(self):
        c = self.conv(OLIO, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT")
        self.assertEqual((c.reliable, c.factor), (True, Decimal("1")))

    def test_oil_total_in_litres(self):
        # Olio girasole 2026: 5.940 LT fatturati a litro + 6 latte da 5 L a pezzo = 5.970 LT.
        lines = [
            row(9, OLIO, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "LT", "2220", "1.81"),
            row(9, OLIO, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", "LT", "3720", "1.80"),
            row(9, OLIO, "OOLIGIR", "OLIO GIRASOLE DORELLA 5LT PET", "NR", "6", "9.10"),
        ]
        conversions = pl.compute_conversions({pl.conversion_key(r) for r in lines}, PRODUCTS, ALIASES)
        total = sum(conversions[pl.conversion_key(r)].quantity(pl.signed_quantity(r.quantita, r.tipo_documento))
                    for r in lines)
        self.assertEqual(total, Decimal("5970"))

    def test_buste_carton_and_kg(self):
        carton = pl.line_conversion(product=BUSTE, unita_misura="CT", descrizione=BUSTE_DESC)
        pack = pl.line_conversion(product=BUSTE, unita_misura="CNF", descrizione=BUSTE_DESC)
        kg = pl.line_conversion(product=BUSTE, unita_misura="KG", descrizione=BUSTE_DESC)
        pieces = pl.line_conversion(product=BUSTE, unita_misura="PZ", descrizione=BUSTE_DESC)
        self.assertEqual((carton.reliable, carton.factor), (True, Decimal("1")))
        self.assertEqual((pack.reliable, pack.factor), (True, Decimal("1")))
        # Prezzo al kg (1,57) e al cartone (30,42) non si confrontano: kg per cartone non noti.
        self.assertFalse(kg.reliable)
        self.assertFalse(pieces.reliable)
        self.assertEqual(kg.comparison_unit, "CT")

    def test_calypso_pack_and_pieces(self):
        cf = self.conv(CALYPSO, "BORBF54", "Calypso calice fluttino bicchiere 113ml 54 pezzi", "CF", fornitore=21)
        pz = self.conv(CALYPSO, "BORCF", "Calypso calice fluttino bicchiere 113ml", "PZ", fornitore=21)
        self.assertEqual(cf.factor, Decimal("54"))
        self.assertEqual(pz.factor, Decimal("1"))
        # 22 CF + 204 PZ = 1.392 pezzi
        self.assertEqual(cf.quantity(22) + pz.quantity(204), Decimal("1392"))

    def test_nr_and_n_dot_are_pieces(self):
        for uom in ("NR", "N.", "n", "PZ."):
            c = pl.line_conversion(product=TANQUERAY, alias=TANQUERAY_ALIAS, unita_misura=uom,
                                   descrizione="GIN TANQUERAY 100 CL")
            self.assertEqual((c.reliable, c.factor), (True, Decimal("1")), uom)

    def test_unknown_or_missing_unit_is_not_reliable(self):
        for uom in ("", None, "OMAGGIO", "SCATOLONE"):
            c = pl.line_conversion(product=TANQUERAY, unita_misura=uom, descrizione="GIN TANQUERAY 100 CL")
            self.assertFalse(c.reliable, uom)

    def test_missing_product_or_unit(self):
        self.assertFalse(pl.line_conversion(product=None, unita_misura="PZ").reliable)
        no_unit = product(9, "SKU-NU", None)
        self.assertFalse(pl.line_conversion(product=no_unit, unita_misura="PZ").reliable)

    def test_manual_pack_factor_wins(self):
        a = alias(1, 9, 1, "PPANVE5", "PANINO 500", fattore=Decimal("5"))
        c = pl.line_conversion(product=MINI_PANINO, alias=a, unita_misura="CT", descrizione="PANINO")
        self.assertEqual((c.reliable, c.factor), (True, Decimal("5")))


class AliasIndexTest(unittest.TestCase):
    def test_code_wins_over_description(self):
        self.assertIs(ALIASES.resolve(9, 58, "OLBAS20", "OLIO GIRASOLE DORELLA 5LT PET"), OLIO_20)

    def test_code_alias_of_another_product_is_ignored(self):
        self.assertIsNone(ALIASES.resolve(9, 999, "OLBAS20", "OLIO GIRASOLE 20LT BASSO"))

    def test_unknown_code_does_not_fall_back_to_description(self):
        # Come la riassociazione: con il codice si cerca solo per codice.
        self.assertIsNone(ALIASES.resolve(9, 58, "NUOVO", "OLIO GIRASOLE 20LT BASSO"))

    def test_line_without_code_matches_normalized_description(self):
        self.assertIs(ALIASES.resolve(9, 58, None, "olio  girasole 20lt basso"), OLIO_20)
        self.assertIs(ALIASES.resolve(9, 58, "", "OLIO GIRASOLE 20LT BASSO"), OLIO_20)
        self.assertIsNone(ALIASES.resolve(10, 58, None, "OLIO GIRASOLE 20LT BASSO"))  # altro fornitore

    def test_approved_alias_preferred(self):
        index = pl.AliasIndex([
            alias(1, 3, 7, None, "PANE BAO", pack=10, status="pending"),
            alias(2, 3, 7, None, "PANE BAO", pack=20, status="approved"),
        ])
        self.assertEqual(index.resolve(3, 7, None, "PANE BAO").id, 2)


class StrictNormalizationTest(unittest.TestCase):
    """normalize_price_for_comparison: il comportamento rigido vale solo per le analisi."""

    def line(self, price, uom, description=""):
        return SimpleNamespace(prezzo_unitario_fatturato=Decimal(price), sconto_percentuale=Decimal("0"),
                               quantita=Decimal("1"), unita_misura_fattura=uom,
                               descrizione_fornitore_raw=description)

    def test_default_unit_count_is_reliable_only_for_anomalies(self):
        line = self.line("26.89", "CT", "PANINO EDNA GELO")
        anomalies = normalize_price_for_comparison(line, MINI_PANINO)
        analyses = normalize_price_for_comparison(line, MINI_PANINO, strict_pack=True)
        # Anomalie invariate (nessuna anomalia esistente cambia).
        self.assertTrue(anomalies.reliable)
        self.assertEqual(anomalies.listino_units_per_invoice_unit, Decimal("1"))
        # Analisi: la confezione non è nota, la conversione non è affidabile.
        self.assertFalse(analyses.reliable)

    def test_zero_price_factor_in_both_modes(self):
        line = self.line("0", "CT", MINI_PANINO_DESC)
        for strict in (False, True):
            res = normalize_price_for_comparison(line, MINI_PANINO, alias=MINI_PANINO_ALIAS, strict_pack=strict)
            self.assertEqual(res.listino_units_per_invoice_unit, Decimal("100"))
            self.assertEqual(res.normalized_unit_price, Decimal("0"))

    def test_factor_matches_price_ratio_when_price_is_positive(self):
        line = self.line("18", "CT", "VINO 6X0,75")
        wine = product(11, "SKU-VINO", "Lt", unit_count=6, volume_ml=750)
        res = normalize_price_for_comparison(line, wine)
        self.assertEqual(res.listino_units_per_invoice_unit, Decimal("4.5"))
        self.assertEqual(res.normalized_unit_price, Decimal("4"))

    def test_box_comparison_from_pieces_needs_a_pack(self):
        box = product(12, "SKU-BOX", "CT", unit_count=1)
        line = self.line("1.20", "PZ", "BICCHIERE")
        self.assertTrue(normalize_price_for_comparison(line, box).reliable)  # anomalie: invariato
        self.assertFalse(normalize_price_for_comparison(line, box, strict_pack=True).reliable)
        line_with_pack = self.line("1.20", "PZ", "BICCHIERE CONF 50")
        res = normalize_price_for_comparison(line_with_pack, box, strict_pack=True)
        self.assertTrue(res.reliable)
        self.assertEqual(res.listino_units_per_invoice_unit, Decimal("1") / Decimal("50"))


class PurchaseLinesSelectTest(unittest.TestCase):
    def test_common_rules_are_in_the_query(self):
        user = SimpleNamespace(tenant_id=1)
        text = sql(pl.purchase_lines_select(user, require_sku=True), literal=True)
        self.assertIn("NOT (EXISTS (SELECT * \nFROM skus_esclusi", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("fatture.tenant_id = 1 OR fatture.tenant_id IS NULL", text)
        self.assertIn("'TD04', 'TD08'", text)
        self.assertIn("LEFT OUTER JOIN products", text)

    def test_other_tenant_only_sees_its_invoices(self):
        text = sql(pl.purchase_lines_select(SimpleNamespace(tenant_id=4)), literal=True)
        self.assertIn("fatture.tenant_id = 4", text)
        self.assertNotIn("tenant_id IS NULL", text)

    def test_options(self):
        text = sql(pl.purchase_lines_select(None, include_excluded=True, include_credit_notes=False,
                                            location_ids=[2], fornitore_ids=[9], skus=["A"]), literal=True)
        self.assertNotIn("skus_esclusi", text)
        self.assertNotIn("tenant_id", text)
        self.assertIn("fatture.tipo_documento NOT IN ('TD04', 'TD08')", text)
        self.assertIn("fatture.location_id IN (2)", text)
        self.assertIn("fatture.fornitore_id IN (9)", text)
        self.assertIn("righe_fattura.sku_interno IN ('A')", text)

    def test_columns(self):
        names = set(pl.purchase_lines_select(None).subquery().c.keys())
        for name in ("riga_id", "fornitore_id", "product_id", "codice_fornitore", "descrizione", "unita_misura",
                     "unita", "quantita", "quantita_firmata", "importo_netto", "netto_unitario", "segno",
                     "is_omaggio", "in_media", "comparison_unit", "data_documento", "location_id"):
            self.assertIn(name, names)


class ConversionTableTest(unittest.TestCase):
    def test_aggregate_query_with_conversion_table(self):
        lines = [
            row(9, MINI_PANINO, "PPANVE", MINI_PANINO_DESC, "CT", "2", "26.89"),
            row(9, OLIO, "OLBAS20", "OLIO GIRASOLE 20LT BASSO", "NR", "1", "36"),
            row(21, BUSTE, None, "Buste d'ambra 90x120", "KG", "30", "1.57"),
        ]
        conversions = pl.compute_conversions({pl.conversion_key(r) for r in lines}, PRODUCTS, ALIASES)
        base = pl.purchase_lines_select(SimpleNamespace(tenant_id=1), require_sku=True).subquery("pl")
        conv = pl.conversion_table(conversions)
        stmt = (
            select(
                base.c.sku_interno,
                func.sum(base.c.importo_netto).label("spesa"),
                func.sum(pl.converted_quantity_sql(base, conv)).label("quantita_confronto"),
            )
            .select_from(base.outerjoin(conv, pl.conversion_join(base, conv)))
            .group_by(base.c.sku_interno)
        )
        text = sql(stmt, literal=True)
        self.assertIn("FROM (VALUES (", text)
        self.assertIn("(9, 1, 'PPANVE', 'PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO', 'CT', 100, true, 'Pz')",
                      text)
        self.assertIn("(9, 58, 'OLBAS20', 'OLIO GIRASOLE 20LT BASSO', 'NR', 20, true, 'Lt')", text)
        self.assertIn("'Buste d''ambra 90x120'", text)  # apice raddoppiato, nessuna iniezione
        self.assertIn("IS NOT DISTINCT FROM", text)
        self.assertIn("CAST(", text)
        self.assertIn("100", text)

    def test_empty_conversion_table_is_valid(self):
        text = sql(select(pl.conversion_table({})), literal=True)
        self.assertIn("VALUES (-1, NULL", text)

    def test_unreliable_conversion_has_null_factor(self):
        key = pl.ConversionKey(21, 700, None, "BUSTE", "KG")
        text = sql(select(pl.conversion_table({key: pl.line_conversion(product=BUSTE, unita_misura="KG")})),
                   literal=True)
        self.assertIn("(21, 700, NULL, 'BUSTE', 'KG', NULL, false, 'CT')", text)


if __name__ == "__main__":
    unittest.main()
