import os
import unittest
from datetime import date
from types import SimpleNamespace

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services.variant_price_import import cut_offer_rows_at


def row(start, end, row_id=1):
    return SimpleNamespace(id=row_id, data_inizio_validita=start, data_scadenza=end)


class OfferRenewalTest(unittest.TestCase):
    """Weekly fruit forms: the new response must not overlap the row approved with an end date."""

    def test_row_still_valid_ends_the_day_before(self):
        old = row(date(2026, 11, 9), date(2026, 11, 29))
        cut_offer_rows_at([old], date(2026, 11, 23))
        self.assertEqual(old.data_scadenza, date(2026, 11, 22))

    def test_row_ending_before_the_new_start_is_untouched(self):
        old = row(date(2026, 11, 9), date(2026, 11, 29))
        cut_offer_rows_at([old], date(2026, 11, 30))
        self.assertEqual(old.data_scadenza, date(2026, 11, 29))

    def test_row_ending_on_the_new_start_day_is_cut(self):
        old = row(date(2026, 11, 9), date(2026, 11, 29))
        cut_offer_rows_at([old], date(2026, 11, 29))
        self.assertEqual(old.data_scadenza, date(2026, 11, 28))

    def test_row_starting_on_or_after_the_new_start_is_refused(self):
        newer = row(date(2026, 11, 23), date(2026, 11, 29), row_id=7)
        with self.assertRaises(ValueError):
            cut_offer_rows_at([newer], date(2026, 11, 23))
        self.assertEqual(newer.data_scadenza, date(2026, 11, 29))

    def test_open_row_is_left_to_the_current_price_logic(self):
        current = row(date(2026, 10, 1), None)
        cut_offer_rows_at([current], date(2026, 11, 23))
        self.assertIsNone(current.data_scadenza)


if __name__ == "__main__":
    unittest.main()
