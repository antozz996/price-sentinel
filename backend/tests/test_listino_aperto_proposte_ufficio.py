"""Listino sempre aperto: l'ufficio decide sui nomi e sui prodotti nuovi proposti dai fornitori."""
import asyncio
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

from app.api.deps import require_admin  # noqa: E402
from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.models import supplier_price_link as spl  # noqa: E402
from app.models.listino import ORIGINE_LISTINO_APERTO  # noqa: E402

ADMIN = SimpleNamespace(id=42, tenant_id=1)
PRODUCT = SimpleNamespace(id=500, sku_interno="FRU-001", canonical_name="Zucchine")


def _result(one=None, many=()):
    result = MagicMock()
    result.scalar_one_or_none.return_value = one
    result.scalars.return_value.all.return_value = list(many)
    return result


def _name_proposal():
    return spl.SupplierProductProposal(id=1, tipo=spl.PROPOSTA_NOME, stato=spl.PROPOSTA_IN_ATTESA, fornitore_id=18,
                                       sku_interno="FRU-001", supplier_product_alias_id=9,
                                       nome_fornitore="Zucchine romanesche cat. I")


def _db(proposal, same_name=(), base=None):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_result(proposal), _result(many=same_name)])
    db.scalar = AsyncMock(return_value=PRODUCT)
    db.get = AsyncMock(return_value=base)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    added = []

    def add(obj):
        obj.id = 77
        added.append(obj)
    db.add.side_effect = add
    return db, added


class RoutesTest(unittest.TestCase):
    def test_office_routes_are_admin_only(self):
        paths = {(route.path, tuple(sorted(route.methods))): route for route in links.router.routes}
        for path, method in (("/proposals/catalog-search", "GET"), ("/proposals/{proposal_id}/approve-name", "POST"),
                             ("/proposals/{proposal_id}/approve-product", "POST"),
                             ("/proposals/{proposal_id}/reject", "POST")):
            deps = [d.call for d in paths[(path, (method,))].dependant.dependencies]
            self.assertIn(require_admin, deps, path)


class OfferFormatTest(unittest.TestCase):
    def test_per_kg_piece_litre_is_one(self):
        for unit in ("KG", "PZ", "L"):
            self.assertEqual(links.new_product_offer(SimpleNamespace(unita_vendita=unit)), (Decimal("1"), unit))

    def test_box_uses_what_is_inside(self):
        proposal = SimpleNamespace(unita_vendita="CASSA", contenuto_quantita=Decimal("6"), contenuto_unita="KG")
        self.assertEqual(links.new_product_offer(proposal), (Decimal("6"), "KG"))

    def test_half_pieces_are_refused(self):
        with self.assertRaises(HTTPException):
            links.validate_new_product(links.NewProduct(nome="Uova", unita_vendita="CT", prezzo=Decimal("5"),
                                                        contenuto_quantita=Decimal("1.5"), contenuto_unita="PZ"))


class ApproveNameTest(unittest.TestCase):
    def test_new_name_is_added_next_to_the_old_one(self):
        base = SimpleNamespace(brand="BIO", pack_qty=None, fattore_confezione=None, volume_ml=None, weight_g=1000,
                               container_type=None)
        proposal = _name_proposal()
        db, added = _db(proposal, base=base)
        asyncio.run(links.approve_name_proposal(1, admin=ADMIN, db=db))
        alias = added[0]
        self.assertEqual((alias.product_id, alias.supplier_id, alias.source), (500, 18, "listino_aperto"))
        self.assertEqual((alias.raw_description, alias.weight_g, alias.supplier_code), ("Zucchine romanesche cat. I", 1000, None))
        self.assertEqual((proposal.stato, proposal.applicato_alias_id, proposal.decisione_by_id),
                         (spl.PROPOSTA_APPROVATA, 77, 42))

    def test_name_of_another_product_is_refused(self):
        db, added = _db(_name_proposal(), same_name=[SimpleNamespace(product_id=999)])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(links.approve_name_proposal(1, admin=ADMIN, db=db))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(added, [])

    def test_name_already_linked_to_the_same_product_adds_nothing(self):
        proposal = _name_proposal()
        db, added = _db(proposal, same_name=[SimpleNamespace(product_id=500, id=12)])
        asyncio.run(links.approve_name_proposal(1, admin=ADMIN, db=db))
        self.assertEqual(added, [])
        self.assertEqual(proposal.applicato_alias_id, 12)

    def test_decided_proposal_is_refused(self):
        proposal = _name_proposal()
        proposal.stato = spl.PROPOSTA_RIFIUTATA
        db, _ = _db(proposal)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(links.approve_name_proposal(1, admin=ADMIN, db=db))
        self.assertEqual(ctx.exception.status_code, 409)


class ApproveProductTest(unittest.TestCase):
    def test_new_product_goes_through_the_price_form_import(self):
        proposal = spl.SupplierProductProposal(id=4, tipo=spl.PROPOSTA_PRODOTTO_NUOVO, stato=spl.PROPOSTA_IN_ATTESA,
                                               fornitore_id=18, nome_fornitore="Pomodoro datterino", unita_vendita="CASSA",
                                               contenuto_quantita=Decimal("3"), contenuto_unita="KG", prezzo=Decimal("7.50"))
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(proposal))
        db.scalar = AsyncMock(side_effect=[PRODUCT, 88])
        db.commit = AsyncMock()
        preview = SimpleNamespace(preview_payload={"errors": []})
        with patch.object(links, "build_variant_preview", AsyncMock(return_value=preview)) as build, \
                patch.object(links, "commit_variant_preview", AsyncMock(return_value={"listino_ids": [321]})) as commit:
            asyncio.run(links.approve_product_proposal(4, links.ProposalProduct(sku_interno="FRU-001"), admin=ADMIN, db=db))
        row = build.await_args.args[1].rows[0]
        self.assertEqual((row.quantity, row.unit, row.price, row.offer_id), (Decimal("3"), "KG", Decimal("7.50"), "LA-4"))
        self.assertEqual(commit.await_args.kwargs["origine"], ORIGINE_LISTINO_APERTO)
        self.assertEqual((proposal.stato, proposal.applicato_listino_id, proposal.applicato_alias_id, proposal.sku_interno),
                         (spl.PROPOSTA_APPROVATA, 321, 88, "FRU-001"))

    def test_import_errors_stop_the_approval(self):
        proposal = spl.SupplierProductProposal(id=4, tipo=spl.PROPOSTA_PRODOTTO_NUOVO, stato=spl.PROPOSTA_IN_ATTESA,
                                               fornitore_id=18, nome_fornitore="X", unita_vendita="KG", prezzo=Decimal("1"))
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(proposal))
        db.scalar = AsyncMock(return_value=PRODUCT)
        preview = SimpleNamespace(preview_payload={"errors": [{"message": "Fornitore non abilitato al prodotto/settore."}]})
        with patch.object(links, "build_variant_preview", AsyncMock(return_value=preview)):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(links.approve_product_proposal(4, links.ProposalProduct(sku_interno="FRU-001"), admin=ADMIN, db=db))
        self.assertIn("non abilitato", ctx.exception.detail)
        self.assertEqual(proposal.stato, spl.PROPOSTA_IN_ATTESA)


if __name__ == "__main__":
    unittest.main()
