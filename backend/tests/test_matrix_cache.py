"""Offline guards for services.matrix_cache (shared cache of the Smart Price Sheet matrix)."""
import unittest
from datetime import date

from app.services import matrix_cache


def params(**over):
    base = dict(tenant_id=1, search=None, category=None, subcategory=None, location_id=None, limit=500,
                offset=0, sort="nome", periodo="tutto", price_on=date(2026, 11, 22), today=date(2026, 11, 21))
    return matrix_cache.make_params(**{**base, **over})


class MatrixCacheTest(unittest.TestCase):
    def test_key_changes_with_day_tenant_location_and_price_day(self):
        key = matrix_cache.cache_key(params())
        for change in ({"today": date(2026, 11, 22)}, {"tenant_id": 2}, {"location_id": 3},
                       {"price_on": date(2026, 11, 30)}, {"offset": 500}, {"sort": "quantita"}):
            self.assertNotEqual(key, matrix_cache.cache_key(params(**change)), change)
        self.assertEqual(key, matrix_cache.cache_key(params()))

    def test_fingerprint_reads_every_source_table(self):
        sql = str(matrix_cache._FINGERPRINT_SQL)
        for table in matrix_cache.SOURCE_TABLES:
            self.assertIn(f"FROM {table}", sql)
        self.assertIn("sum(xmin::text::bigint)", sql)

    def test_route_serves_the_cached_endpoint(self):
        from app.api.v1 import smart_price_sheet as sheet
        route = next(r for r in sheet.router.routes if getattr(r, "path", None) == "/matrix")
        self.assertIs(route.endpoint, sheet.matrix_endpoint)

    def test_heavy_views_are_cached_and_warmable(self):
        from app.api.v1 import intelligence, product_identity
        served = {
            (intelligence.router, "/variance-loss"): intelligence.variance_loss_endpoint,
            (intelligence.router, "/efficiency-leaderboard"): intelligence.efficiency_leaderboard_endpoint,
            (intelligence.router, "/product-consumption"): intelligence.product_consumption_endpoint,
            (product_identity.router, "/products"): product_identity.list_products_endpoint,
        }
        for (router, path), endpoint in served.items():
            route = next(r for r in router.routes if getattr(r, "path", None) == path and "GET" in r.methods)
            self.assertIs(route.endpoint, endpoint, path)
        for kind in ("matrix", "variance-loss", "efficiency-leaderboard", "product-consumption", "products"):
            self.assertIn(kind, matrix_cache.COMPUTERS)

    def test_view_params_separate_kinds_and_filters(self):
        from types import SimpleNamespace
        user = SimpleNamespace(tenant_id=1, ruolo="admin", location_id=None)
        base = matrix_cache.view_params("product-consumption", user, location_ids=None, data_da=date(2026, 1, 1))
        self.assertEqual(base["data_da"], "2026-01-01")
        for other in (matrix_cache.view_params("variance-loss", user, location_ids=None, data_da=date(2026, 1, 1)),
                      matrix_cache.view_params("product-consumption", user, location_ids="3", data_da=date(2026, 1, 1))):
            self.assertNotEqual(matrix_cache.cache_key(base), matrix_cache.cache_key(other))


if __name__ == "__main__":
    unittest.main()
