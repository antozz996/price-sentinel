"""The supplier's wording shown on their price pages never exposes our internal product codes."""
import unittest

from app.api.v1.supplier_price_forms import _supplier_wording


class SupplierWordingTest(unittest.TestCase):
    def test_internal_codes_are_hidden(self):
        # Code of a merged product saved as wording on an old approved form (Ma.Gi.Fer., Selenella).
        for code in ("SG3-2654BF669A9AB4E2", " CAN-9-7399-1794578309 ", "", None):
            self.assertIsNone(_supplier_wording(code))

    def test_real_wording_is_kept(self):
        self.assertEqual(_supplier_wording(" PAT. SELENELLA "), "PAT. SELENELLA")
        self.assertEqual(_supplier_wording("SG3 PATATE"), "SG3 PATATE")


if __name__ == "__main__":
    unittest.main()
