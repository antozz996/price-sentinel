"""Listino sempre aperto: endpoint del link fisso (senza database)."""
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from pydantic import ValidationError  # noqa: E402

from app.api.deps import require_admin  # noqa: E402
from app.api.v1 import supplier_price_links as api  # noqa: E402
from app.api.v1.router import api_router  # noqa: E402
from app.models.supplier_price_link import SupplierPriceLink  # noqa: E402


def _dependencies(route):
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        found.add(dep.call)
        stack.extend(dep.dependencies)
    return found


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.routes = {(r.path, tuple(sorted(r.methods))): r for r in api_router.routes
                       if r.path.startswith("/supplier-price-links")}

    def test_public_routes_need_no_login(self):
        for path, methods in (("/public/{token}", ("GET",)), ("/public/{token}/submit", ("POST",)),
                              ("/public/{token}/confirm-unchanged", ("POST",))):
            route = self.routes[(f"/supplier-price-links{path}", methods)]
            self.assertNotIn(require_admin, _dependencies(route), path)

    def test_admin_routes_need_admin(self):
        for path, methods in (("/supplier/{fornitore_id}", ("GET",)), ("/supplier/{fornitore_id}", ("POST",)),
                              ("/supplier/{fornitore_id}/revoke", ("POST",))):
            route = self.routes[(f"/supplier-price-links{path}", methods)]
            self.assertIn(require_admin, _dependencies(route), path)


class TokenTest(unittest.TestCase):
    def test_stored_token_round_trip(self):
        token = "t" * 43
        link = SupplierPriceLink(token_hash=api._hash(token), token_encrypted=api._encrypt_token(token),
                                 created_at=datetime.now(timezone.utc), attivo=True)
        self.assertEqual(api._link_token(link), token)
        self.assertEqual(api._link_view(link)["path"], f"/fornitore/prezzi/{token}")

    def test_token_of_another_link_is_ignored(self):
        link = SupplierPriceLink(token_hash=api._hash("a" * 43), token_encrypted=api._encrypt_token("b" * 43),
                                 created_at=datetime.now(timezone.utc), attivo=True)
        self.assertIsNone(api._link_token(link))


class PayloadTest(unittest.TestCase):
    def test_price_must_be_positive(self):
        with self.assertRaises(ValidationError):
            api.PriceUpdate(listino_id=1, prezzo=Decimal("0"))

    def test_at_least_one_change(self):
        with self.assertRaises(ValidationError):
            api.PriceUpdates(modifiche=[])

    def test_valid_change(self):
        update = api.PriceUpdate(listino_id=1, prezzo=Decimal("2.5"))
        self.assertFalse(update.non_trattato)


if __name__ == "__main__":
    unittest.main()
