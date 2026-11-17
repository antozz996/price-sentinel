"""Listino sempre aperto: il fornitore propone una nuova unità di vendita, l'ufficio la approva."""
import asyncio
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402

from app.api.deps import require_admin  # noqa: E402
from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.models import supplier_price_link as spl  # noqa: E402
from app.models.listino import ORIGINE_LISTINO_APERTO  # noqa: E402

ADMIN = SimpleNamespace(id=42, tenant_id=1)
NOW = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
TODAY = links.today_rome()


def _result(one=None, many=()):
    result = MagicMock()
    result.scalar_one_or_none.return_value = one
    result.scalars.return_value = MagicMock(all=MagicMock(return_value=list(many)),
                                            __iter__=lambda self: iter(list(many)))
    return result


class SaleUnitTest(unittest.TestCase):
    def test_per_kg_needs_nothing_inside(self):
        self.assertEqual(links.validate_sale_unit("kg", Decimal("5"), "PZ", "Zucchine"), ("KG", None, None))

    def test_box_needs_content(self):
        self.assertEqual(links.validate_sale_unit("cassa", Decimal("5"), "kg", "Patate"), ("CASSA", Decimal("5"), "KG"))
        with self.assertRaises(HTTPException):
            links.validate_sale_unit("CT", None, None, "Fragole")

    def test_unit_and_price_box_together_are_refused(self):
        update = links.PriceUpdate(listino_id=1, prezzo=Decimal("2"),
                                   unita=links.UnitChange(unita_vendita="KG", prezzo=Decimal("2")))
        link = SimpleNamespace(id=5, fornitore_id=18)
        row = SimpleNamespace(id=1, sku_interno="FRU-1", supplier_product_alias_id=None, descrizione="Zucchine")
        db = MagicMock()
        request = SimpleNamespace(client=None)
        with patch.object(links, "_active_link", AsyncMock(return_value=(link, "Ma.Gi.Fer."))), \
                patch.object(links, "_active_supplier_rows", AsyncMock(return_value=[row])), \
                patch.object(links, "_approved_names", AsyncMock(return_value={})), \
                patch.object(links, "_offer_formats", AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(links.submit_open_price_list("t" * 43, links.PriceUpdates(modifiche=[update]), request, db))
        self.assertIn("nuova unità", ctx.exception.detail)


class SaveUnitProposalTest(unittest.TestCase):
    def test_last_unit_sent_wins(self):
        old = spl.SupplierProductProposal(id=3, stato=spl.PROPOSTA_IN_ATTESA)
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(many=[old]))
        db.flush = AsyncMock()
        added = []
        db.add.side_effect = lambda obj: (setattr(obj, "id", 9), added.append(obj))
        row = SimpleNamespace(id=70, sku_interno="FRU-1", supplier_product_alias_id=4)
        change = links.UnitChange(unita_vendita="CASSA", contenuto_quantita=Decimal("6"), contenuto_unita="PZ",
                                  prezzo=Decimal("15"))
        asyncio.run(links._save_unit_proposal(db, SimpleNamespace(id=5, fornitore_id=18), row, change, "MELONI", NOW, None))
        new = added[0]
        self.assertEqual((new.tipo, new.unita_vendita, new.contenuto_quantita, new.prezzo),
                         (spl.PROPOSTA_UNITA, "CASSA", Decimal("6"), Decimal("15")))
        self.assertEqual((old.stato, old.sostituita_da_id), (spl.PROPOSTA_SOSTITUITA, 9))


class ApproveUnitTest(unittest.TestCase):
    def _run(self, alias_source="normalized_sheet_offer", expiry=TODAY + timedelta(days=10)):
        proposal = spl.SupplierProductProposal(id=11, tipo=spl.PROPOSTA_UNITA, stato=spl.PROPOSTA_IN_ATTESA,
                                               fornitore_id=18, listino_id_origine=70, unita_vendita="CASSA",
                                               contenuto_quantita=Decimal("6"), contenuto_unita="PZ", prezzo=Decimal("15"))
        row = SimpleNamespace(id=70, fornitore_id=18, sku_interno="FRU-1", supplier_product_alias_id=4,
                              data_inizio_validita=TODAY - timedelta(days=5), data_scadenza=expiry, descrizione="MELONI")
        base = SimpleNamespace(source=alias_source, supplier_code="OFF-9", raw_description="MELONE GIALLETTO", brand=None)
        new_row = SimpleNamespace(data_scadenza=None)
        pending_change = spl.SupplierPriceChange(stato=spl.STATO_PROGRAMMATO)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(proposal), _result(), _result(many=[new_row]),
                                            _result(many=[pending_change])])
        db.get = AsyncMock(side_effect=[row, base])
        db.scalar = AsyncMock(side_effect=[SimpleNamespace(id=500, sku_interno="FRU-1"), 88])
        db.commit = AsyncMock()
        preview = SimpleNamespace(preview_payload={"errors": []})
        with patch.object(links, "_newer_row_exists", AsyncMock(return_value=False)), \
                patch.object(links, "build_variant_preview", AsyncMock(return_value=preview)) as build, \
                patch.object(links, "commit_variant_preview", AsyncMock(return_value={"listino_ids": [321]})) as commit:
            asyncio.run(links.approve_unit_proposal(11, admin=ADMIN, db=db))
        return proposal, new_row, pending_change, build.await_args.args[1].rows[0], commit

    def test_offer_from_price_forms_keeps_its_code_and_expiry(self):
        proposal, new_row, pending_change, offer, commit = self._run()
        self.assertEqual((offer.offer_id, offer.quantity, offer.unit, offer.price), ("OFF-9", Decimal("6"), "PZ", Decimal("15")))
        self.assertEqual(commit.await_args.kwargs["origine"], ORIGINE_LISTINO_APERTO)
        self.assertEqual(new_row.data_scadenza, TODAY + timedelta(days=10))
        self.assertEqual((pending_change.stato, pending_change.motivo_trattenuta),
                         (spl.STATO_SOSTITUITO, links.MOTIVO_UNITA_CAMBIATA))
        self.assertEqual((proposal.stato, proposal.applicato_listino_id, proposal.applicato_alias_id),
                         (spl.PROPOSTA_APPROVATA, 321, 88))

    def test_generic_row_gets_a_new_offer(self):
        _, new_row, _, offer, _ = self._run(alias_source="invoice", expiry=None)
        self.assertEqual(offer.offer_id, "LA-U-11")
        self.assertIsNone(new_row.data_scadenza)

    def test_expired_price_is_refused(self):
        proposal = spl.SupplierProductProposal(id=11, tipo=spl.PROPOSTA_UNITA, stato=spl.PROPOSTA_IN_ATTESA,
                                               fornitore_id=18, listino_id_origine=70)
        row = SimpleNamespace(id=70, fornitore_id=18, data_scadenza=date(2020, 1, 1))
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(proposal))
        db.get = AsyncMock(return_value=row)
        with patch.object(links, "_newer_row_exists", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(links.approve_unit_proposal(11, admin=ADMIN, db=db))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_route_is_admin_only(self):
        route = next(r for r in links.router.routes if r.path == "/proposals/{proposal_id}/approve-unit")
        self.assertIn(require_admin, [d.call for d in route.dependant.dependencies])


if __name__ == "__main__":
    unittest.main()
