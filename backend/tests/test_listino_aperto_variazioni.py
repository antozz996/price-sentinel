"""Listino sempre aperto: pagina «Variazioni listini» (senza database)."""
import inspect
import os
import unittest
from datetime import date
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.api.deps import require_admin  # noqa: E402
from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.services.open_price_list_rules import annual_impact, previous_fixed_date, reminder_deadline  # noqa: E402

D = date


class DatesTest(unittest.TestCase):
    def test_previous_fixed_date(self):
        self.assertEqual(previous_fixed_date(D(2026, 11, 14)), D(2026, 11, 1))
        self.assertEqual(previous_fixed_date(D(2026, 11, 15)), D(2026, 11, 15))
        self.assertEqual(previous_fixed_date(D(2026, 11, 30)), D(2026, 11, 15))

    def test_reminders_from_the_10th_and_the_25th(self):
        self.assertIsNone(reminder_deadline(D(2026, 11, 9)))
        self.assertEqual(reminder_deadline(D(2026, 11, 10)), D(2026, 11, 15))
        self.assertEqual(reminder_deadline(D(2026, 11, 14)), D(2026, 11, 15))
        self.assertIsNone(reminder_deadline(D(2026, 11, 15)))
        self.assertIsNone(reminder_deadline(D(2026, 11, 24)))
        self.assertEqual(reminder_deadline(D(2026, 12, 25)), D(2027, 1, 1))


class ImpactTest(unittest.TestCase):
    def test_increase_on_last_year_spend(self):
        self.assertEqual(annual_impact(Decimal("1200"), Decimal("10"), Decimal("11")), Decimal("120.00"))

    def test_decrease_is_negative(self):
        self.assertEqual(annual_impact(Decimal("500"), "4", "3"), Decimal("-125.00"))

    def test_no_purchases_or_closing_has_no_impact(self):
        self.assertIsNone(annual_impact(None, Decimal("10"), Decimal("11")))
        self.assertIsNone(annual_impact(Decimal("-30"), Decimal("10"), Decimal("11")))
        self.assertIsNone(annual_impact(Decimal("100"), Decimal("10"), None))


class RoutesTest(unittest.TestCase):
    def test_overview_routes_are_admin_only(self):
        paths = {route.path: route for route in links.router.routes}
        for path in ("/overview", "/overview/count"):
            deps = [d.call for d in paths[path].dependant.dependencies]
            self.assertIn(require_admin, deps, path)

    def test_spend_is_per_supplier(self):
        source = inspect.getsource(links._spend_by_supplier_sku)
        self.assertIn("group_by(lines.c.fornitore_id, lines.c.sku_interno)", source)


if __name__ == "__main__":
    unittest.main()
