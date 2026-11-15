"""PR9: Ordini, Riconciliazione ordini/fatture, God Mode, Recensioni.

Casi reali del rapporto schermate 14/11/2026 (export di produzione del 14/11):
- A11 Cortina cooler (riga 35, fattura VE.MO 6816): 3 CF a 43,50 contro listino
  1,23 PZ, collegamento BORCCIP35 con fattore confezione 35: contestato 126,81 -> 1,35;
- A11 PANE BAO (riga 6133, fattura MELIUS 1/30152): 2 CT a 25,50 contro listino 0,65
  senza unità, collegamento SVHAPHO da 30 pezzi: 49,70 -> 12,00;
- A12 ricezione non registrata: nessun "fatturato in più" (prima 51,00 su PANE BAO);
- A13 note di credito TD04/TD08 non associabili (NC Navas n.146, 18.093,39 EUR);
- M27 righe uguali legittime (Navas 3339 'sam02' 6 x 9,8367 due volte);
- B11 confidence solo sulle righe di fattura, giorni del filtro in ora italiana;
- God Mode: 1.775.670,31 TD01 + 5.827,44 TD24 - 138.572,98 TD04 (era sommata);
- M24/M25/M26 Recensioni e Registro ordini.
Nessun database.
"""
import asyncio
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1.god_mode import invoice_totals_select  # noqa: E402
from app.api.v1.reconciliations import rome_day_bounds  # noqa: E402
from app.models.fatture import TipoDocumento  # noqa: E402
from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import purchase_order_reconciliation as por  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402
from app.services.order_quantities import order_quantity_summary  # noqa: E402
from app.services.product_review_stats import OrderIndex, pick_best_listino, pick_usual_suppliers  # noqa: E402
from app.services.purchase_lines import AliasIndex  # noqa: E402

TOL_ABS, TOL_PCT = Decimal("0.01"), Decimal("1.0")


def product(pid, sku, unit, name):
    return Product(id=pid, sku_interno=sku, canonical_name=name, comparison_unit=unit, unit_count=1)


def alias(aid, supplier, pid, code, description, pack=None, fattore=None, volume_ml=None):
    return SupplierProductAlias(
        id=aid, supplier_id=supplier, product_id=pid, supplier_code=code, raw_description=description,
        normalized_description=normalize_text(description), pack_qty=pack, fattore_confezione=fattore,
        volume_ml=volume_ml, status="approved", source="manual",
    )


def line(qty, unit, price, description, discount=0, code=None):
    return SimpleNamespace(
        quantita=Decimal(str(qty)), unita_misura_fattura=unit, prezzo_unitario_fatturato=Decimal(str(price)),
        sconto_percentuale=Decimal(str(discount)), descrizione_fornitore_raw=description, codice_fornitore_raw=code,
    )


# ── Dati reali ──
CORTINA = product(929, "CAN-21-153-1793797700", "Pz", "Cortina bicchiere cooler 40 38,5cl")
CORTINA_DESC = "Cortina bicchiere cooler 40 38,5cl 35 pezzi 190240T14021990"
CORTINA_ALIASES = [
    alias(2007, 21, 929, "BORCCIP35", CORTINA_DESC, fattore=Decimal("35"), volume_ml=385),
    alias(2469, 21, 929, "BORBC40", "Cortina bicchiere cooler 40 38,5cl mm 65x162,5h 190240CUC021990", volume_ml=385),
]
CORTINA_LINE = line(3, "CF", "43.50", CORTINA_DESC, code="BORCCIP35")
CORTINA_LISTINO = por.ExpectedPrice(Decimal("1.2300"), "listino_master:3238", "PZ")

PANE_BAO = product(7, "SG3-80E96D7103B1CF44", "Pz", "PANE BAO")
PANE_BAO_DESC = "PANE BAO EUROPASTRY 40grx30pz surg."
PANE_BAO_ALIAS = alias(2520, 9, 7, "SVHAPHO", PANE_BAO_DESC, pack=30)
PANE_BAO_LINE = line(2, "CT", "25.50", PANE_BAO_DESC, code="SVHAPHO")
PANE_BAO_LISTINO = por.ExpectedPrice(Decimal("0.6500"), "listino_master:29", None)  # listino senza unità


class ReconciliationPriceTest(unittest.TestCase):
    """A11: listino e fattura confrontati nella stessa unità (base comune line_conversion)."""

    def test_cortina_confronto_a_pezzo(self):
        found = AliasIndex(CORTINA_ALIASES).resolve(21, 929, "BORCCIP35", CORTINA_DESC)
        self.assertEqual(found.id, 2007)
        check = por.compare_line_price(CORTINA_LINE, CORTINA, found, CORTINA_LISTINO)
        self.assertEqual(check.status, "ok")
        self.assertEqual(check.factor, Decimal("35"))
        self.assertEqual(check.invoiced, Decimal("1.242857"))
        self.assertEqual(check.units, Decimal("105"))
        # Prima: (43,50 - 1,23) x 3 = 126,81 contestati. Ora 0,012857 x 105 pezzi.
        self.assertEqual(por.price_overcharge(check, TOL_ABS, TOL_PCT), Decimal("1.35"))
        # Con tolleranza 2% non c'è nessuna anomalia.
        self.assertIsNone(por.price_overcharge(check, TOL_ABS, Decimal("2")))

    def test_pane_bao_listino_senza_unita_vale_unita_della_voce(self):
        found = AliasIndex([PANE_BAO_ALIAS]).resolve(9, 7, "SVHAPHO", PANE_BAO_DESC)
        check = por.compare_line_price(PANE_BAO_LINE, PANE_BAO, found, PANE_BAO_LISTINO)
        self.assertEqual(check.status, "ok")
        self.assertEqual(check.invoiced, Decimal("0.850000"))
        self.assertEqual(check.comparison_unit, "Pz")
        # Prima 49,70 (25,50 - 0,65 per 2 cartoni). Ora (0,85 - 0,65) x 60 pezzi.
        self.assertEqual(por.price_overcharge(check, TOL_ABS, TOL_PCT), Decimal("12.00"))

    def test_sconto_di_riga_applicato(self):
        discounted = line(2, "CT", "25.50", PANE_BAO_DESC, discount=20, code="SVHAPHO")
        check = por.compare_line_price(discounted, PANE_BAO, PANE_BAO_ALIAS, PANE_BAO_LISTINO)
        self.assertEqual(check.invoiced, Decimal("0.680000"))  # 25,50 x 0,8 / 30

    def test_confezione_sconosciuta_non_si_confronta(self):
        # Stessa riga a cartone senza collegamento né pezzi in descrizione: niente fattore.
        unknown = line(2, "CT", "25.50", "PANE BAO SURGELATO")
        check = por.compare_line_price(unknown, PANE_BAO, None, PANE_BAO_LISTINO)
        self.assertEqual(check.status, "unverifiable")
        self.assertIsNone(check.delta)
        self.assertIsNone(por.price_overcharge(check, TOL_ABS, TOL_PCT))
        self.assertEqual(check.evidence()["status"], "unverifiable")

    def test_senza_listino_nessun_confronto(self):
        check = por.compare_line_price(PANE_BAO_LINE, PANE_BAO, PANE_BAO_ALIAS, None)
        self.assertEqual(check.status, "no_reference")
        self.assertIsNone(por.price_overcharge(check, TOL_ABS, TOL_PCT))

    def test_stessa_unita_resta_come_prima(self):
        # Caso dell'E2E: 2 pz a 12 contro listino 10 pz -> 4,00 contestati.
        item = product(4, "SKU4", "pz", "Price")
        check = por.compare_line_price(line(2, "pz", "12", "Price"), item, None, por.ExpectedPrice(Decimal("10"), "l", "pz"))
        self.assertEqual(por.price_overcharge(check, TOL_ABS, TOL_PCT), Decimal("4.00"))


class ReconciliationQuantityTest(unittest.TestCase):
    """A12 ricezione non registrata, M27 righe uguali, B11 confidence."""

    def outcome(self, delta, duplicate=False, check=None, compatible=True):
        return por.line_outcome(
            compatible=compatible, duplicate=duplicate, quantity_delta=delta, net_price=Decimal("25.50"),
            check=check or por.PriceCheck("no_reference"), tolerance_absolute=TOL_ABS, tolerance_percent=TOL_PCT,
        )

    def test_ricezione_non_registrata_nessuna_contestazione(self):
        delta, duplicate = por.quantity_outcome(
            invoiced=Decimal("2"), received=None, ordered=Decimal("2"), consumed_before=Decimal("0"),
            is_last=True, signature_seen=False,
        )
        self.assertIsNone(delta)
        self.assertFalse(duplicate)
        # Prima: quantity_overbilled con 2 x 25,50 = 51,00 contestati.
        self.assertEqual(self.outcome(delta), ("matched", None, None))
        self.assertIsNone(por._received(None))
        evidence = por._with_checks({"explicit_product_id": 7}, por.PriceCheck("no_reference"), None)
        self.assertEqual(evidence["receipt_status"], por.AWAITING_RECEIPT)
        self.assertEqual(evidence["explicit_product_id"], 7)
        self.assertIn("In attesa di ricezione", por._reason_with_receipt("SKU canonico", None))

    def test_ricezione_non_registrata_il_prezzo_si_controlla(self):
        check = por.compare_line_price(PANE_BAO_LINE, PANE_BAO, PANE_BAO_ALIAS, PANE_BAO_LISTINO)
        self.assertEqual(self.outcome(None, check=check), ("price_mismatch", "price_overcharge", Decimal("12.00")))

    def test_fatturato_in_piu_contestato_sul_netto(self):
        delta, _ = por.quantity_outcome(
            invoiced=Decimal("3"), received=Decimal("2"), ordered=Decimal("3"), consumed_before=Decimal("0"),
            is_last=True, signature_seen=False,
        )
        self.assertEqual(delta, Decimal("1"))
        self.assertEqual(self.outcome(delta), ("quantity_mismatch", "quantity_overbilled", Decimal("25.50")))

    def test_righe_uguali_entro_il_ricevuto_non_sono_doppioni(self):
        # Navas 3339: 'sam02' 6 x 9,8367 due volte, ordinati e ricevuti 12.
        first = por.quantity_outcome(invoiced=Decimal("6"), received=Decimal("12"), ordered=Decimal("12"),
                                     consumed_before=Decimal("0"), is_last=False, signature_seen=False)
        second = por.quantity_outcome(invoiced=Decimal("6"), received=Decimal("12"), ordered=Decimal("12"),
                                      consumed_before=Decimal("6"), is_last=True, signature_seen=True)
        self.assertEqual(first, (Decimal("0"), False))
        self.assertEqual(second, (Decimal("0"), False))

    def test_doppione_solo_sull_eccedenza(self):
        # Ricevuti 6: la seconda riga uguale cade tutta oltre il ricevuto.
        second = por.quantity_outcome(invoiced=Decimal("6"), received=Decimal("6"), ordered=Decimal("6"),
                                      consumed_before=Decimal("6"), is_last=True, signature_seen=True)
        self.assertTrue(second[1])
        self.assertEqual(self.outcome(second[0], duplicate=second[1]), ("ambiguous", "duplicate_invoice_line", None))
        # Riga diversa oltre il ricevuto: fatturato in più, non doppione.
        other = por.quantity_outcome(invoiced=Decimal("4"), received=Decimal("6"), ordered=Decimal("6"),
                                     consumed_before=Decimal("6"), is_last=True, signature_seen=False)
        self.assertEqual(other, (Decimal("4"), False))
        # Ricezione non registrata: il limite è l'ordinato.
        awaiting = por.quantity_outcome(invoiced=Decimal("6"), received=None, ordered=Decimal("6"),
                                        consumed_before=Decimal("6"), is_last=True, signature_seen=True)
        self.assertEqual(awaiting, (None, True))

    def test_fatturato_in_meno_sull_ultima_riga(self):
        first = por.quantity_outcome(invoiced=Decimal("4"), received=Decimal("10"), ordered=Decimal("10"),
                                     consumed_before=Decimal("0"), is_last=False, signature_seen=False)
        last = por.quantity_outcome(invoiced=Decimal("4"), received=Decimal("10"), ordered=Decimal("10"),
                                    consumed_before=Decimal("4"), is_last=True, signature_seen=False)
        self.assertEqual(first, (Decimal("0"), False))
        self.assertEqual(last, (Decimal("-2"), False))

    def test_unita_diverse_prima_della_quantita(self):
        self.assertEqual(self.outcome(None, compatible=False), ("unit_mismatch", "unit_mismatch", None))

    def test_confidence_solo_righe_di_fattura(self):
        # Prima: (0,60 + 9 righe mancanti a 1) / 10 = 0,96.
        self.assertEqual(por.matching_confidence([Decimal("0.60")]), Decimal("0.60"))
        self.assertEqual(por.matching_confidence([]), Decimal("0"))

    def test_giorni_del_filtro_in_ora_italiana(self):
        start, end = rome_day_bounds(date(2026, 6, 15), date(2026, 6, 15))
        self.assertEqual(start.astimezone(timezone.utc), datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(end.astimezone(timezone.utc), datetime(2026, 6, 15, 22, 0, tzinfo=timezone.utc))
        sent = datetime(2026, 6, 14, 22, 30, tzinfo=timezone.utc)  # 15/06 alle 00:30 in Italia
        self.assertTrue(start <= sent < end)
        self.assertEqual(rome_day_bounds(None, None), (None, None))


class CreditNoteTest(unittest.TestCase):
    """A13: una nota di credito non si associa a un ordine."""

    def test_tipi(self):
        for tipo, expected in ((TipoDocumento.TD04, True), (TipoDocumento.TD08, True),
                               (TipoDocumento.TD01, False), (TipoDocumento.TD24, False)):
            self.assertEqual(por.is_credit_note(SimpleNamespace(tipo_documento=tipo)), expected, tipo)

    def test_attach_rifiuta_td04_con_409(self):
        nc_navas_146 = SimpleNamespace(id=66, tipo_documento=TipoDocumento.TD04, fornitore_id=22, location_id=3)
        with self.assertRaises(por.ReconciliationError) as raised:
            asyncio.run(por.attach_invoice(
                None, SimpleNamespace(), nc_navas_146, allow_reassociate=False,
                tolerance_absolute=TOL_ABS, tolerance_percent=TOL_PCT,
            ))
        self.assertEqual((raised.exception.code, raised.exception.status), ("credit_note_not_attachable", 409))


class GodModeTest(unittest.TestCase):
    def test_volume_con_segno_e_note_di_credito_a_parte(self):
        sql = str(invoice_totals_select().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("CASE WHEN (fatture.tipo_documento IN ('TD04', 'TD08')) THEN -1 ELSE 1 END * fatture.totale_imponibile", sql)
        self.assertIn("count(fatture.id) FILTER (WHERE (fatture.tipo_documento NOT IN ('TD04', 'TD08')))", sql)
        self.assertIn("count(fatture.id) FILTER (WHERE fatture.tipo_documento IN ('TD04', 'TD08'))", sql)

    def test_numeri_di_produzione(self):
        from app.services.purchase_lines import document_sign
        totals = {TipoDocumento.TD01: Decimal("1775670.31"), TipoDocumento.TD24: Decimal("5827.44"),
                  TipoDocumento.TD04: Decimal("138572.98")}
        volume = sum(document_sign(tipo) * value for tipo, value in totals.items())
        self.assertEqual(volume, Decimal("1642924.77"))  # prima 1.920.070,73
        # Tolte anche le 39 fatture doppie (19.700,97, già cancellate in produzione): 1.623,2k.
        self.assertEqual(volume - Decimal("19700.97"), Decimal("1623223.80"))


class OrderRegistryTest(unittest.TestCase):
    """M26: i colli non sommano kg, pezzi e litri; gli omaggi sono "di cui"."""

    def riga(self, qty, uom, price=5.0, omaggio=False, received=None):
        return SimpleNamespace(quantita=qty, uom=uom, prezzo_inserito=0.0 if omaggio else price,
                               stato_ottimizzazione="omaggio" if omaggio else "concordato", quantita_ricevuta=received)

    def test_unita_separate(self):
        # Come la fattura VE.MO 2777: 24 PZ + 3 conf + 2 CT + 30 Kg, più 2 CT omaggio.
        summary = order_quantity_summary([
            self.riga(24, "Pz"), self.riga(3, "conf"), self.riga(2, "CT", received=2),
            self.riga(30, "Kg"), self.riga(2, "CT", omaggio=True),
        ])
        self.assertEqual(summary["totale_colli"], 7.0)  # prima 61
        self.assertEqual(summary["colli_omaggio"], 2.0)
        self.assertEqual(summary["totale_colli_ricevuti"], 2.0)
        self.assertEqual(summary["quantita_per_uom"], {"PZ": 24.0, "CNF": 3.0, "CT": 4.0, "KG": 30.0})

    def test_unita_vuota_e_ct(self):
        self.assertEqual(order_quantity_summary([self.riga(5, None)])["totale_colli"], 5.0)


class ProductReviewTest(unittest.TestCase):
    """M24 fornitore abituale / miglior listino, M25 ordini distinti."""

    def test_omaggio_non_e_un_secondo_ordine(self):
        when = datetime(2026, 11, 10, 9, 0)
        rows = [
            SimpleNamespace(ordine_id=1, product_id=50, sku_interno="SKU-ACQUA", data_ordine=when),
            SimpleNamespace(ordine_id=1, product_id=50, sku_interno="SKU-ACQUA", data_ordine=when),  # riga omaggio
        ]
        self.assertEqual(OrderIndex(rows).stats(50, "SKU-ACQUA"), (1, when))

    def test_gruppi_della_stessa_voce_si_uniscono(self):
        old, new = datetime(2026, 9, 1), datetime(2026, 11, 1)
        rows = [
            SimpleNamespace(ordine_id=1, product_id=50, sku_interno="SKU-A", data_ordine=new),
            SimpleNamespace(ordine_id=2, product_id=None, sku_interno="SKU-A", data_ordine=old),
            SimpleNamespace(ordine_id=3, product_id=50, sku_interno="SKU-VECCHIO", data_ordine=old),
        ]
        index = OrderIndex(rows)
        # Prima: l'ultimo gruppo sovrascriveva gli altri (1 ordine, data vecchia).
        self.assertEqual(index.stats(50, "SKU-A"), (3, new))
        self.assertEqual(index.product_ids, {50})

    def test_fornitore_abituale_mini_panino_melius(self):
        # MINI PANINO EDNA BURGHER: 66 righe negli ultimi 12 mesi, tutte MELIUS (9);
        # prima si mostrava MARR, il listino più basso (0,21 senza unità).
        rows = [("SG3-52506F3CBE1143E1", 9, 66, date(2026, 11, 12))]
        self.assertEqual(pick_usual_suppliers(rows), {"SG3-52506F3CBE1143E1": 9})

    def test_fornitore_abituale_parita(self):
        rows = [("SKU", 5, 10, date(2026, 10, 1)), ("SKU", 7, 10, date(2026, 11, 1)), ("SKU", 3, 2, date(2026, 11, 14))]
        self.assertEqual(pick_usual_suppliers(rows), {"SKU": 7})

    def listino(self, lid, supplier, price, unit, start=date(2026, 10, 27), alias_id=None):
        return SimpleNamespace(id=lid, fornitore_id=supplier, prezzo_pattuito=Decimal(price), unita_misura=unit,
                               data_inizio_validita=start, supplier_product_alias_id=alias_id)

    def test_miglior_listino_nell_unita_di_confronto(self):
        # 0,26 a pezzo non perde contro 26,60 a cartone da 100: si confronta a pezzo.
        panino = product(1, "SG3-52506F3CBE1143E1", "Pz", "MINI PANINO EDNA BURGHER")
        carton = alias(2558, 9, 1, "PPANVE", "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO", pack=100)
        rows = [self.listino(10, 9, "26.60", "CT", alias_id=2558), self.listino(11, 13, "0.29", "PZ")]
        self.assertEqual(pick_best_listino(rows, panino, {2558: carton}).id, 10)

    def test_listini_senza_unita_di_fornitori_diversi_non_si_confrontano(self):
        # I tre listini reali del MINI PANINO (MARR 0,21, MELIUS 0,25, 0,29) non hanno unità.
        panino = product(1, "SG3-52506F3CBE1143E1", "Pz", "MINI PANINO EDNA BURGHER")
        rows = [self.listino(1, 15, "0.21", ""), self.listino(2, 9, "0.25", ""), self.listino(3, 13, "0.29", "")]
        self.assertIsNone(pick_best_listino(rows, panino, {}))
        # Un solo fornitore: si mostra il suo listino più recente.
        single = [self.listino(2, 9, "0.25", ""), self.listino(4, 9, "0.27", "", start=date(2026, 11, 1))]
        self.assertEqual(pick_best_listino(single, panino, {}).id, 4)


if __name__ == "__main__":
    unittest.main()
