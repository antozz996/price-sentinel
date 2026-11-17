"""Listino sempre aperto: il fornitore corregge il suo nome di un prodotto e propone prodotti nuovi."""
import asyncio
import inspect
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402

from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.models import supplier_price_link as spl  # noqa: E402

NOW = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
LINK = SimpleNamespace(id=5, fornitore_id=18)
ROW = SimpleNamespace(id=70, sku_interno="FRU-001", supplier_product_alias_id=9, descrizione="ZUCCHINE")


def _new(**kw):
    data = {"nome": "  Zucchine   romanesche ", "unita_vendita": "kg", "prezzo": Decimal("2.10")}
    data.update(kw)
    return links.NewProduct(**data)


def _db(pending=None):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = pending
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    added = []

    def add(obj):
        obj.id = 99
        added.append(obj)
    db.add.side_effect = add
    return db, added


class NewProductTest(unittest.TestCase):
    def test_simple_product_needs_only_name_unit_price(self):
        product = links.validate_new_product(_new(contenuto_quantita=Decimal("5"), contenuto_unita="PZ"))
        self.assertEqual((product.nome, product.unita_vendita), ("Zucchine romanesche", "KG"))
        self.assertIsNone(product.contenuto_quantita)  # al kg il contenuto non serve

    def test_box_needs_what_is_inside(self):
        with self.assertRaises(HTTPException) as ctx:
            links.validate_new_product(_new(unita_vendita="CT"))
        self.assertEqual(ctx.exception.status_code, 422)
        product = links.validate_new_product(_new(unita_vendita="cassa", contenuto_quantita=Decimal("6"), contenuto_unita="kg"))
        self.assertEqual((product.unita_vendita, product.contenuto_unita), ("CASSA", "KG"))

    def test_unknown_unit_is_refused(self):
        with self.assertRaises(HTTPException):
            links.validate_new_product(_new(unita_vendita="CONF"))

    def test_only_new_products_can_be_sent(self):
        payload = links.PriceUpdates(nuovi=[_new()])
        self.assertEqual(payload.modifiche, [])


class NameProposalTest(unittest.TestCase):
    def test_new_name_is_saved_for_review(self):
        db, added = _db()
        self.assertTrue(asyncio.run(links._save_name_proposal(db, LINK, ROW, "ZUCCH.", "Zucchine romanesche cat. I", NOW, None)))
        proposal = added[0]
        self.assertEqual((proposal.tipo, proposal.stato), (spl.PROPOSTA_NOME, spl.PROPOSTA_IN_ATTESA))
        self.assertEqual((proposal.nome_precedente, proposal.sku_interno, proposal.supplier_product_alias_id),
                         ("ZUCCH.", "FRU-001", 9))

    def test_same_name_as_today_saves_nothing(self):
        db, added = _db()
        self.assertFalse(asyncio.run(links._save_name_proposal(db, LINK, ROW, "Zucchine", " zucchine ", NOW, None)))
        self.assertEqual(added, [])

    def test_last_name_sent_wins(self):
        old = spl.SupplierProductProposal(id=3, nome_fornitore="Zucchine A", stato=spl.PROPOSTA_IN_ATTESA)
        db, added = _db(old)
        self.assertTrue(asyncio.run(links._save_name_proposal(db, LINK, ROW, None, "Zucchine B", NOW, None)))
        self.assertEqual((old.stato, old.sostituita_da_id), (spl.PROPOSTA_SOSTITUITA, 99))

    def test_back_to_old_name_cancels_the_pending_one(self):
        old = spl.SupplierProductProposal(id=3, nome_fornitore="Zucchine A", stato=spl.PROPOSTA_IN_ATTESA)
        db, added = _db(old)
        self.assertTrue(asyncio.run(links._save_name_proposal(db, LINK, ROW, "Zucchine", "Zucchine", NOW, None)))
        self.assertEqual(old.stato, spl.PROPOSTA_SOSTITUITA)
        self.assertEqual(added, [])


class OurNameNeverChangesTest(unittest.TestCase):
    def test_submit_never_writes_our_product_name(self):
        source = inspect.getsource(links.submit_open_price_list) + inspect.getsource(links._save_name_proposal)
        for forbidden in ("canonical_name", "descrizione =", "raw_description =", "Product("):
            self.assertNotIn(forbidden, source)

    def test_one_pending_name_per_row(self):
        index = next(i for i in spl.SupplierProductProposal.__table__.indexes if i.name == "uq_supplier_product_proposal_nome")
        self.assertTrue(index.unique)


if __name__ == "__main__":
    unittest.main()
