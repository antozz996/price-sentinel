"""Listino sempre aperto: pannello dell'ufficio (via libera, rifiuto, altro prezzo, link)."""
import asyncio
import inspect
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.api.deps import require_admin  # noqa: E402
from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.models import supplier_price_link as spl  # noqa: E402
from app.services import open_price_list_activation as activation  # noqa: E402


def _session(change):
    db = MagicMock()
    db.get = AsyncMock(return_value=change)
    db.execute = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _change(stato, prezzo_vecchio="10"):
    return spl.SupplierPriceChange(
        id=7, fornitore_id=3, sku_interno="SKU1", chiave_offerta="SKU1#", stato=stato,
        tipo=spl.TIPO_AUMENTO, prezzo_vecchio=Decimal(prezzo_vecchio), prezzo_nuovo=Decimal("15"),
        decorrenza=activation.today_rome(),
    )


ADMIN = SimpleNamespace(id=42, tenant_id=1)


class RoutesTest(unittest.TestCase):
    def test_panel_routes_are_admin_only(self):
        paths = {(route.path, tuple(sorted(route.methods))): route for route in links.router.routes}
        for path, method in (("/suppliers", "GET"), ("/changes/{change_id}/approve", "POST"),
                             ("/changes/{change_id}/reject", "POST"), ("/changes/{change_id}/force", "POST")):
            deps = [d.call for d in paths[(path, (method,))].dependant.dependencies]
            self.assertIn(require_admin, deps, path)


class AllowedActionsTest(unittest.TestCase):
    def test_only_held_changes_get_the_green_light(self):
        self.assertEqual(links.AZIONI_PERMESSE["approva"], (spl.STATO_TRATTENUTO,))

    def test_scheduled_increases_can_be_refused_or_repriced(self):
        for action in ("rifiuta", "altro_prezzo"):
            self.assertIn(spl.STATO_PROGRAMMATO, links.AZIONI_PERMESSE[action])
            self.assertNotIn(spl.STATO_APPLICATO, links.AZIONI_PERMESSE[action])

    def test_decided_change_is_refused(self):
        db = _session(_change(spl.STATO_APPLICATO))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(links._change_for_decision(db, 7, "rifiuta"))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_lock_before_row(self):
        source = inspect.getsource(links._change_for_decision)
        self.assertLess(source.index("pg_advisory_xact_lock"), source.index("with_for_update=True"))

    def test_forced_price_must_be_positive(self):
        with self.assertRaises(ValidationError):
            links.ForcedPrice(prezzo=Decimal("0"))


class DecisionsTest(unittest.TestCase):
    def test_reject_records_who_decided(self):
        change = _change(spl.STATO_TRATTENUTO)
        asyncio.run(links.reject_change(7, admin=ADMIN, db=_session(change)))
        self.assertEqual((change.stato, change.decisione_by_id), (spl.STATO_RIFIUTATO, 42))
        self.assertIsNotNone(change.decisione_at)

    def test_approve_schedules_and_applies_if_due(self):
        change = _change(spl.STATO_TRATTENUTO)
        with patch.object(links, "apply_change_now", AsyncMock(return_value={"applicate": 1})) as apply_now:
            res = asyncio.run(links.approve_change(7, admin=ADMIN, db=_session(change)))
        self.assertEqual(change.stato, spl.STATO_PROGRAMMATO)
        self.assertEqual(change.decisione_by_id, 42)
        apply_now.assert_awaited_once()
        self.assertEqual(res["esito"], {"applicate": 1})

    def test_force_same_old_price_means_refused(self):
        change = _change(spl.STATO_PROGRAMMATO)
        db = _session(change)
        asyncio.run(links.force_change_price(7, links.ForcedPrice(prezzo=Decimal("10")), admin=ADMIN, db=db))
        self.assertEqual(change.stato, spl.STATO_RIFIUTATO)
        db.add.assert_not_called()

    def test_force_replaces_with_office_price(self):
        change = _change(spl.STATO_TRATTENUTO)
        db = _session(change)
        added = []

        def add(obj):
            obj.id = 99
            added.append(obj)
        db.add.side_effect = add
        with patch.object(links, "apply_change_now", AsyncMock(return_value={})):
            asyncio.run(links.force_change_price(7, links.ForcedPrice(prezzo=Decimal("11")), admin=ADMIN, db=db))
        forced = added[0]
        self.assertEqual((change.stato, change.sostituito_da_id), (spl.STATO_SOSTITUITO, 99))
        self.assertEqual((forced.stato, forced.tipo, forced.prezzo_nuovo), (spl.STATO_PROGRAMMATO, spl.TIPO_AUMENTO, Decimal("11")))
        self.assertIsNone(forced.motivo_trattenuta)
        self.assertEqual(forced.decisione_by_id, 42)
        # Un aumento deciso dall'ufficio vale comunque dalla prossima data fissa.
        self.assertGreater(forced.decorrenza, activation.today_rome())

    def test_force_lower_price_is_a_decrease_valid_today(self):
        change = _change(spl.STATO_TRATTENUTO)
        db = _session(change)
        added = []
        db.add.side_effect = lambda obj: (setattr(obj, "id", 99), added.append(obj))
        with patch.object(links, "apply_change_now", AsyncMock(return_value={})):
            asyncio.run(links.force_change_price(7, links.ForcedPrice(prezzo=Decimal("9")), admin=ADMIN, db=db))
        self.assertEqual((added[0].tipo, added[0].decorrenza), (spl.TIPO_RIBASSO, activation.today_rome()))


class ApplyNowTest(unittest.TestCase):
    def test_apply_now_uses_the_same_rules_as_the_daily_job(self):
        source = inspect.getsource(activation.apply_change_now)
        self.assertIn("_apply_one(", source)


if __name__ == "__main__":
    unittest.main()
