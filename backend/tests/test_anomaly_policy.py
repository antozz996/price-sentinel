import asyncio
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1.fatture import list_fatture, list_righe_fattura
from app.models.anomalie import Anomalia, StatoValidazione
from app.services.anomaly_policy import (
    MIN_ANOMALY_TOTAL,
    MIN_ANOMALY_UNIT_DELTA,
    is_material_price_increase,
    operational_anomaly_filter,
    stale_unworked_anomaly_conditions,
)


ADMIN = SimpleNamespace(ruolo=SimpleNamespace(value="admin"), location_id=None)


def compiled(statement):
    return statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ).string


class _QueryReached(Exception):
    """Raised once the handler has built the anomaly query without errors."""


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0]

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _ScriptedDb:
    """Returns the scripted results, then stops at the next query."""

    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        if not self._results:
            raise _QueryReached
        return _Rows(self._results.pop(0))


class MaterialityRuleTest(unittest.TestCase):
    def test_rounding_noise_is_not_an_anomaly(self):
        self.assertFalse(is_material_price_increase(Decimal("0.00")))
        self.assertFalse(is_material_price_increase(Decimal("0.04")))
        self.assertFalse(is_material_price_increase(Decimal("0.0999")))

    def test_exactly_ten_cents_is_not_material(self):
        # Cases #224 (STRUTTO 4 x 0.025) and #294 (Spirale 1 x 0.10).
        self.assertFalse(is_material_price_increase(Decimal("0.10")))
        self.assertFalse(is_material_price_increase(Decimal("4") * Decimal("0.025"), Decimal("0.025")))
        self.assertFalse(is_material_price_increase(Decimal("0.1000"), Decimal("0.1000")))

    def test_above_ten_cents_is_material(self):
        self.assertTrue(is_material_price_increase(Decimal("0.1001")))
        self.assertTrue(is_material_price_increase(Decimal("0.11"), Decimal("0.11")))
        self.assertTrue(is_material_price_increase(Decimal("5.00")))
        self.assertTrue(is_material_price_increase(5.0, 0.5))

    def test_threshold_is_judged_at_stored_scale(self):
        # A normalised price with long decimals must not create an anomaly that
        # is stored as exactly 0.1000 and then hidden by the SQL filter.
        self.assertFalse(is_material_price_increase(Decimal("0.100000000004"), Decimal("0.025000000001")))
        self.assertTrue(is_material_price_increase(Decimal("0.10005"), Decimal("0.10005")))

    def test_sub_half_cent_unit_gap_is_rounding(self):
        # Case #72 (Moet): 8.1431 vs 8.14 on 90 bottles = 0.2828 EUR.
        self.assertFalse(is_material_price_increase(Decimal("0.2828"), Decimal("0.0031")))
        # Ice Imperial: 0.0017 EUR x 60.
        self.assertFalse(is_material_price_increase(Decimal("0.102"), Decimal("0.0017")))
        self.assertFalse(is_material_price_increase(Decimal("0.50"), Decimal("0.0049")))
        # Half a cent and a real one-cent increase stay anomalies.
        self.assertTrue(is_material_price_increase(Decimal("0.15"), Decimal("0.0050")))
        self.assertTrue(is_material_price_increase(Decimal("0.30"), Decimal("0.0100")))

    def test_unit_gap_is_optional_for_old_callers(self):
        self.assertTrue(is_material_price_increase(Decimal("0.2828")))

    def test_sql_filter_uses_the_shared_threshold(self):
        sql = compiled(select(Anomalia.id).where(operational_anomaly_filter()))
        self.assertIn(f"abs(anomalie.delta_totale) > {MIN_ANOMALY_TOTAL}", sql)
        self.assertNotIn("abs(anomalie.delta_totale) >=", sql)
        self.assertIn(f"abs(anomalie.delta_prezzo) >= {MIN_ANOMALY_UNIT_DELTA}", sql)

    def test_micro_anomalies_stay_visible_only_while_being_handled(self):
        sql = compiled(select(Anomalia.id).where(operational_anomaly_filter()))
        for open_state in (
            StatoValidazione.proposta_aggiornamento,
            StatoValidazione.contestata,
            StatoValidazione.in_reclamo,
        ):
            self.assertIn(open_state.name, sql)
        for hidden_state in (
            StatoValidazione.da_verificare,
            StatoValidazione.in_parking,
            StatoValidazione.accettata,
            StatoValidazione.risolta,
        ):
            self.assertNotIn(hidden_state.name, sql)


class StaleAnomalyCleanupTest(unittest.TestCase):
    def test_only_unworked_anomalies_of_the_line_are_deleted(self):
        sql = compiled(select(Anomalia.id).where(*stale_unworked_anomaly_conditions(42)))
        self.assertIn("anomalie.riga_fattura_id = 42", sql)
        self.assertIn(StatoValidazione.da_verificare.name, sql)
        self.assertIn(StatoValidazione.in_parking.name, sql)
        for worked_state in (
            StatoValidazione.contestata,
            StatoValidazione.in_reclamo,
            StatoValidazione.risolta,
        ):
            self.assertNotIn(worked_state.name, sql)


class InvoiceEndpointsBuildTheirQueriesTest(unittest.TestCase):
    """Regression: PR #72 referenced Decimal without importing it in fatture.py."""

    def test_invoice_list_reaches_the_database(self):
        with self.assertRaises(_QueryReached):
            asyncio.run(
                list_fatture(
                    response=Response(),
                    location_id=None,
                    fornitore_id=None,
                    tipo_documento=None,
                    marker=None,
                    data_da=None,
                    data_a=None,
                    search=None,
                    limit=5,
                    offset=0,
                    current_user=ADMIN,
                    db=_ScriptedDb(),
                )
            )

    def test_invoice_lines_reach_the_anomaly_query(self):
        db = _ScriptedDb([SimpleNamespace(id=1)], [SimpleNamespace(id=7)])
        with self.assertRaises(_QueryReached):
            asyncio.run(list_righe_fattura(fattura_id=1, current_user=ADMIN, db=db))
        self.assertEqual(db._results, [])


if __name__ == "__main__":
    unittest.main()
