"""Unit tests per l'importazione nuovo prodotto dal selettore ordini e invio richiesta prezzo (RFQ) multi-fornitore di settore.
"""

import asyncio
from types import SimpleNamespace
from typing import List

from app.api.v1.ordini import (
    CreateSectorProductRequest,
    crea_prodotto_settore,
    SectorPriceQuoteRequest,
    genera_richiesta_prezzo_settore,
)
from app.models.products import Product
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.purchase_policy import SupplierCategoryCapability
from app.models.utenti import Utente


class DummyScalarResult:
    def __init__(self, item=None, items=None):
        self._item = item
        self._items = items or ([] if item is None else [item])

    def first(self):
        return self._item

    def all(self):
        return self._items


class MockDbSession:
    def __init__(self, location=None, fornitori=None, capabilities=None, products=None):
        self.location = location
        self.fornitori = fornitori or []
        self.capabilities = capabilities or []
        self.products = {p.id: p for p in (products or [])}
        self.added = []
        self._next_id = 500

    async def get(self, model, key):
        if model == Location and self.location and key == self.location.id:
            return self.location
        if model == Product and key in self.products:
            return self.products[key]
        return None

    async def scalar(self, statement):
        stmt_str = str(statement).lower()
        if "from products" in stmt_str:
            target_val = None
            if hasattr(statement, "_where_criteria"):
                for crit in statement._where_criteria:
                    if hasattr(crit, "right") and hasattr(crit.right, "value"):
                        target_val = crit.right.value
            if target_val is not None:
                for p in self.products.values():
                    if getattr(p, 'sku_interno', None) == target_val or getattr(p, 'normalized_name', None) == target_val:
                        return p
            return None
        return None

    async def scalars(self, statement):
        stmt_str = str(statement).lower()
        if "from fornitori" in stmt_str:
            return DummyScalarResult(items=self.fornitori)
        if "from supplier_category_capabilities" in stmt_str:
            return DummyScalarResult(items=self.capabilities)
        if "from listino_master" in stmt_str:
            return DummyScalarResult(items=[])
        return DummyScalarResult(items=[])

    def add(self, entity):
        if hasattr(entity, 'id') and getattr(entity, 'id', None) is None:
            entity.id = self._next_id
            self._next_id += 1
        self.added.append(entity)
        if isinstance(entity, Product):
            self.products[entity.id] = entity

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, entity):
        pass


async def test_crea_nuovo_prodotto_settore():
    db = MockDbSession()
    user = Utente(id=1, email="manager@test.it", ruolo="manager", ruolo_dettagliato="responsabile_settore")

    # TEST 1: Creazione nuovo prodotto con generazione automatica SKU
    req = CreateSectorProductRequest(
        canonical_name="Gin Mare Capri Special Edition 70cl",
        order_name="GIN MARE CAPRI",
        category="Beverage",
        subcategory="Alcolici & Superalcolici",
        brand="Gin Mare",
        comparison_unit="BT",
        initial_quantity=2.0
    )

    res = await crea_prodotto_settore(data=req, db=db, user=user)

    assert res.id is not None
    assert res.canonical_name == "Gin Mare Capri Special Edition 70cl"
    assert res.order_name == "GIN MARE CAPRI"
    assert res.category == "Beverage"
    assert res.subcategory == "Alcolici & Superalcolici"
    assert res.brand == "Gin Mare"
    assert res.comparison_unit == "BT"
    assert res.sku_interno.startswith("SKU-BEV-")
    assert res.initial_quantity == 2.0
    assert "con successo" in res.message

    # TEST 2: Inserimento prodotto con stesso nome normalizzato -> riutilizza esistente e aggiorna
    req_duplicate = CreateSectorProductRequest(
        canonical_name="gin mare capri special edition 70cl",
        order_name="GIN MARE CAPRI",
        category="Beverage",
        subcategory="Alcolici & Superalcolici",
        comparison_unit="BT",
        initial_quantity=5.0
    )

    res_dup = await crea_prodotto_settore(data=req_duplicate, db=db, user=user)
    assert res_dup.id == res.id, "Deve riconoscere il prodotto esistente senza generare duplicati"
    assert res_dup.initial_quantity == 5.0
    assert "già presente" in res_dup.message

    print("✅ TEST PASSED: Creazione e normalizzazione nuovo prodotto dal selettore verificata!")


async def test_richiesta_prezzo_multi_fornitore():
    loc = SimpleNamespace(id=1, nome_struttura="Beach Club Playa", indirizzo="Lungomare 42", citta="Rimini")
    
    # Fornitore 1: Abilitato per Beverage (con WhatsApp e Email)
    f1 = Fornitore(id=10, nome_azienda="Beverage Distribuzione SRL", partita_iva="11122233344", email_contatto="ordini@bevdistrib.it", telefono_contatto="+393401112233", attivo_whitelist=True)
    cap1 = SupplierCategoryCapability(id=1, supplier_id=10, category="Beverage", enabled=True)

    # Fornitore 2: Abilitato per Beverage (solo WhatsApp)
    f2 = Fornitore(id=20, nome_azienda="Drink Service SpA", partita_iva="55566677788", email_contatto=None, telefono_contatto="3498887766", attivo_whitelist=True)
    cap2 = SupplierCategoryCapability(id=2, supplier_id=20, category="Beverage", enabled=True)

    # Fornitore 3: Abilitato solo per Food
    f3 = Fornitore(id=30, nome_azienda="Food Carni SRL", partita_iva="99900011122", email_contatto="food@carni.it", telefono_contatto="+393339998877", attivo_whitelist=True)
    cap3 = SupplierCategoryCapability(id=3, supplier_id=30, category="Food", enabled=True)

    db = MockDbSession(
        location=loc,
        fornitori=[f1, f2, f3],
        capabilities=[cap1, cap2, cap3],
        products=[]
    )
    user = SimpleNamespace(id=1, email="buyer@playa.it", nome_completo="Mario Rossi", ruolo="manager")

    req = SectorPriceQuoteRequest(
        canonical_name="Gin Mare Capri 70cl",
        order_name="GIN MARE CAPRI",
        category="Beverage",
        subcategory="Alcolici & Superalcolici",
        brand="Gin Mare",
        comparison_unit="BT",
        location_id=1,
        quantita_stimata=6.0,
        specifiche_extra="Richiesto cartone originale da 6 bottiglie"
    )

    res = await genera_richiesta_prezzo_settore(data=req, db=db, user=user)

    # Verifiche di settore
    assert res.total_fornitori_settore == 2, "Solo f1 e f2 abilitati per Beverage devono essere inclusi"
    assert res.fornitori_con_whatsapp == 2
    assert res.fornitori_con_email == 1
    assert "Beach Club Playa" in res.location_nome

    # Verifica testo broadcast WhatsApp
    assert "RICHIESTA QUOTAZIONE PREZZO" in res.broadcast_whatsapp_text
    assert "Gin Mare Capri 70cl" in res.broadcast_whatsapp_text
    assert "6.00 BT" in res.broadcast_whatsapp_text
    assert "Beach Club Playa" in res.broadcast_whatsapp_text

    # Verifica singoli fornitori e link
    sup1 = next(s for s in res.fornitori if s.supplier_id == 10)
    assert sup1.supplier_name == "Beverage Distribuzione SRL"
    assert "https://wa.me/393401112233" in sup1.whatsapp_url
    assert "mailto:ordini@bevdistrib.it" in sup1.email_mailto_url
    assert sup1.has_capability is True

    sup2 = next(s for s in res.fornitori if s.supplier_id == 20)
    assert sup2.supplier_name == "Drink Service SpA"
    assert "https://wa.me/393498887766" in sup2.whatsapp_url
    assert sup2.email_mailto_url == ""

    # Verifica Email broadcast subject & body
    assert "Beach Club Playa" in res.broadcast_email_subject
    assert "Gin Mare Capri 70cl" in res.broadcast_email_body
    assert "Mario Rossi" in res.broadcast_email_body

    print("✅ TEST PASSED: Calcolo fornitori di settore, routing WhatsApp ed Email RFQ verificato con successo!")


if __name__ == "__main__":
    asyncio.run(test_crea_nuovo_prodotto_settore())
    asyncio.run(test_richiesta_prezzo_multi_fornitore())
