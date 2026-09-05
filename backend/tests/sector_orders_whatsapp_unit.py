"""Unit test per i nomi prodotto negli ordini di settore.

Verifica che il nome rapido interno (``order_name``) serva solo alla ricerca e
che anteprima e messaggio WhatsApp usino sempre il nome canonico completo.
"""

import asyncio
from types import SimpleNamespace

from app.api.v1.ordini import (
    SectorOrderDraftRequest,
    SectorOrderItem,
    elabora_ordine_settore,
)
from app.models.products import Product, SupplierProductAlias
from app.models.fornitori import Fornitore
from app.models.location import Location


class DummyScalarResult:
    def __init__(self, item=None, items=None):
        self._item = item
        self._items = items or ([] if item is None else [item])

    def first(self):
        return self._item

    def all(self):
        return self._items


class DummyExecuteResult:
    def __init__(self, item=None):
        self._item = item

    def scalars(self):
        return DummyScalarResult(self._item)


class FakeDbSession:
    def __init__(self, location, fornitori, products, aliases, listini=None):
        self.location = location
        self.fornitori = fornitori
        self.products = {p.id: p for p in products}
        self.aliases = aliases
        self.listini = listini or []

    async def get(self, model, key):
        if model == Location and key == self.location.id:
            return self.location
        if model == Product and key in self.products:
            return self.products[key]
        return None

    async def scalars(self, statement):
        # Interpret basic select queries for test mocks
        stmt_str = str(statement)
        if "FROM fornitori" in stmt_str:
            return DummyScalarResult(items=self.fornitori)
        if "FROM supplier_product_aliases" in stmt_str:
            target_pid = None
            if hasattr(statement, "_where_criteria"):
                for crit in statement._where_criteria:
                    if hasattr(crit, "left") and "product_id" in str(crit.left):
                        target_pid = getattr(crit.right, "value", None)
            matched_alias = next((a for a in self.aliases if a.product_id == target_pid), None) if target_pid is not None else None
            return DummyScalarResult(item=matched_alias)
        if "FROM product_purchase_policies" in stmt_str:
            return DummyScalarResult(item=None)
        return DummyScalarResult(item=None)

    async def execute(self, statement):
        return DummyExecuteResult(item=None)


async def test_whatsapp_name_resolution():
    location = SimpleNamespace(id=1, nome_struttura="Cucina Centrale", indirizzo="Via Roma 1", citta="Milano")
    fornitore = SimpleNamespace(id=10, nome_azienda="Fornitore Food SRL", partita_iva="12345678901", email_contatto="info@food.it", telefono_contatto="+393401234567")
    
    # La descrizione alias è volutamente diversa: sull'ordine deve comunque
    # comparire esattamente il nome canonico mostrato sotto al nome rapido.
    p1 = Product(id=101, sku_interno="SKU-G1", canonical_name="Guanti Monouso Nitrile L", order_name="GUANTI", comparison_unit="CT")
    alias1 = SupplierProductAlias(id=1, supplier_id=10, product_id=101, supplier_code="COD-G1", raw_description="GUANTI NITRILE L NERO 100PZ", status="approved")
    
    # Prodotto 2: Ha order_name="BURRO", canonical_name="Burro Chiarificato 500g", nessun alias
    p2 = Product(id=102, sku_interno="SKU-B1", canonical_name="Burro Chiarificato 500g", order_name="BURRO", comparison_unit="pz")

    db = FakeDbSession(
        location=location,
        fornitori=[fornitore],
        products=[p1, p2],
        aliases=[alias1]
    )

    req = SectorOrderDraftRequest(
        location_id=1,
        settore="Cucina",
        data_consegna="2026-08-30",
        note="Consegna entro le ore 10:00",
        items=[
            SectorOrderItem(product_id=101, order_name="GUANTI", canonical_name="Nome alterato dal client", quantita=5.0, preferred_supplier_id=10),
            SectorOrderItem(product_id=102, order_name="BURRO", canonical_name="Burro Chiarificato 500g", quantita=10.0, preferred_supplier_id=10)
        ]
    )

    user = SimpleNamespace(id=1, ruolo="admin", ruolo_dettagliato="admin")

    res = await elabora_ordine_settore(data=req, db=db, _user=user)

    assert len(res.fornitori_ordini) == 1
    bundle = res.fornitori_ordini[0]
    msg = bundle.whatsapp_message

    print("--- WhatsApp Message Output ---")
    print(msg)
    print("-------------------------------")

    assert bundle.items[0].nome_prodotto == "Guanti Monouso Nitrile L"
    assert bundle.items[0].codice_fornitore == "COD-G1"
    assert "Guanti Monouso Nitrile L" in msg, "Deve usare il nome canonico completo"
    assert "Burro Chiarificato 500g" in msg, "Deve usare il nome canonico se manca l'alias"
    assert "GUANTI NITRILE L NERO 100PZ" not in msg, "La descrizione alias non deve sostituire il nome canonico"
    assert "Nome alterato dal client" not in msg, "Il nome deve essere letto dal database"
    assert "× GUANTI [" not in msg and "× GUANTI\n" not in msg, "NON deve usare il nome rapido interno 'GUANTI'"
    assert "× BURRO [" not in msg and "× BURRO\n" not in msg, "NON deve usare il nome rapido interno 'BURRO'"

    print("✅ TEST PASSED: I nomi rapidi d'ordine dati dall'utente non vengono copiati su WhatsApp!")


async def test_water_promo_5_plus_1():
    location = SimpleNamespace(id=1, nome_struttura="Ristorante Marechiaro", indirizzo="Via Marina 5", citta="Napoli")
    fornitore = SimpleNamespace(id=20, nome_azienda="Navas Beverage SRL", partita_iva="09876543210", email_contatto="ordini@navas.it", telefono_contatto="+393339998877")

    # Prodotti acqua
    p_ferrarelle = Product(id=201, sku_interno="ACQ-FERR-050", canonical_name="Acqua Ferrarelle 0.50 PET x 24", order_name="FERRARELLE 0.50", category="Beverage", comparison_unit="CT")
    p_lete = Product(id=202, sku_interno="ACQ-LETE-150", canonical_name="Acqua Lete 1.5L PET x 6", order_name="LETE 1.5L", category="Beverage", comparison_unit="CT")
    # Prodotto non-acqua con nome fuorviante (es. bicchiere acqua nei materiali di consumo)
    p_bicchieri = Product(id=203, sku_interno="BIC-ACQ-200", canonical_name="Bicchiere Acqua 200ml Monouso", order_name="BICCHIERI", category="Materiali di consumo", comparison_unit="CT")

    db = FakeDbSession(
        location=location,
        fornitori=[fornitore],
        products=[p_ferrarelle, p_lete, p_bicchieri],
        aliases=[]
    )
    user = SimpleNamespace(id=1, ruolo="admin", ruolo_dettagliato="admin")

    # TEST 1: Esattamente 5 box di acqua Ferrarelle -> 1 box omaggio a prezzo 0.00
    req1 = SectorOrderDraftRequest(
        location_id=1,
        settore="Beverage",
        data_consegna="2026-09-06",
        items=[
            SectorOrderItem(product_id=201, canonical_name="Acqua Ferrarelle 0.50 PET x 24", quantita=5.0, comparison_unit="CT", prezzo_unitario=4.50, preferred_supplier_id=20)
        ]
    )
    res1 = await elabora_ordine_settore(data=req1, db=db, _user=user)
    bundle1 = res1.fornitori_ordini[0]
    assert len(bundle1.items) == 2, "Dovrebbero esserci 2 righe: 5 box acquistati + 1 box omaggio"
    omaggio_item = bundle1.items[1]
    assert omaggio_item.is_omaggio is True
    assert omaggio_item.quantita == 1.0
    assert omaggio_item.prezzo_unitario == 0.0
    assert omaggio_item.subtotale == 0.0
    assert bundle1.totale_ordine == round(5.0 * 4.50, 2), "L'omaggio non deve aumentare il totale da pagare"
    assert bundle1.totale_colli == 6.0, "I colli totali devono includere la scatola omaggio (5+1=6)"
    assert "🎁 *(OMAGGIO PROMO 5+1 — GRATIS)*" in bundle1.whatsapp_message
    assert "(Include 1 box di acqua in OMAGGIO)" in bundle1.whatsapp_message

    # TEST 2: 12 box totali misti (7 Ferrarelle + 5 Lete) -> 2 box omaggio (12 // 5 = 2)
    req2 = SectorOrderDraftRequest(
        location_id=1,
        settore="Beverage",
        data_consegna="2026-09-06",
        items=[
            SectorOrderItem(product_id=201, canonical_name="Acqua Ferrarelle 0.50 PET x 24", quantita=7.0, comparison_unit="CT", prezzo_unitario=4.50, preferred_supplier_id=20),
            SectorOrderItem(product_id=202, canonical_name="Acqua Lete 1.5L PET x 6", quantita=5.0, comparison_unit="CT", prezzo_unitario=2.00, preferred_supplier_id=20)
        ]
    )
    res2 = await elabora_ordine_settore(data=req2, db=db, _user=user)
    bundle2 = res2.fornitori_ordini[0]
    assert len(bundle2.items) == 3, "2 righe acquistate + 1 riga omaggio"
    omaggio2 = bundle2.items[2]
    assert omaggio2.is_omaggio is True
    assert omaggio2.quantita == 2.0, "12 box divisi per 5 = 2 box omaggio"
    assert omaggio2.prezzo_unitario == 0.0
    assert omaggio2.product_id == 201, "Se non specificato, sceglie l'acqua con quantità maggiore (Ferrarelle 7 > Lete 5)"
    assert bundle2.totale_colli == 14.0, "7 + 5 + 2 omaggio = 14 colli"

    # TEST 3: Meno di 5 box (4 box Ferrarelle) -> 0 omaggi
    req3 = SectorOrderDraftRequest(
        location_id=1,
        settore="Beverage",
        data_consegna="2026-09-06",
        items=[
            SectorOrderItem(product_id=201, canonical_name="Acqua Ferrarelle 0.50 PET x 24", quantita=4.0, comparison_unit="CT", prezzo_unitario=4.50, preferred_supplier_id=20)
        ]
    )
    res3 = await elabora_ordine_settore(data=req3, db=db, _user=user)
    bundle3 = res3.fornitori_ordini[0]
    assert len(bundle3.items) == 1, "4 box non raggiungono la soglia promozionale di 5"
    assert not any(it.is_omaggio for it in bundle3.items)

    # TEST 4: Bicchieri acqua (non beverage) -> non conteggiati come acqua potabile
    req4 = SectorOrderDraftRequest(
        location_id=1,
        settore="Materiali di consumo",
        data_consegna="2026-09-06",
        items=[
            SectorOrderItem(product_id=203, canonical_name="Bicchiere Acqua 200ml Monouso", quantita=10.0, comparison_unit="CT", prezzo_unitario=15.00, preferred_supplier_id=20)
        ]
    )
    res4 = await elabora_ordine_settore(data=req4, db=db, _user=user)
    bundle4 = res4.fornitori_ordini[0]
    assert len(bundle4.items) == 1
    assert not any(it.is_omaggio for it in bundle4.items)

    # TEST 5: Selezione esplicita della referenza omaggio (water_freebie_product_id)
    req5 = SectorOrderDraftRequest(
        location_id=1,
        settore="Beverage",
        data_consegna="2026-09-06",
        water_freebie_product_id=202,  # Utente sceglie Acqua Lete come omaggio
        items=[
            SectorOrderItem(product_id=201, canonical_name="Acqua Ferrarelle 0.50 PET x 24", quantita=7.0, comparison_unit="CT", prezzo_unitario=4.50, preferred_supplier_id=20),
            SectorOrderItem(product_id=202, canonical_name="Acqua Lete 1.5L PET x 6", quantita=5.0, comparison_unit="CT", prezzo_unitario=2.00, preferred_supplier_id=20)
        ]
    )
    res5 = await elabora_ordine_settore(data=req5, db=db, _user=user)
    bundle5 = res5.fornitori_ordini[0]
    omaggio5 = bundle5.items[2]
    assert omaggio5.is_omaggio is True
    assert omaggio5.product_id == 202, "Deve rispettare la scelta esplicita dell'utente (Acqua Lete)"
    assert omaggio5.quantita == 2.0

    print("✅ TEST PASSED: Regola promozionale acqua 5+1 (1 box omaggio ogni 5 box) verificata con successo in tutti i casi!")


if __name__ == "__main__":
    asyncio.run(test_whatsapp_name_resolution())
    asyncio.run(test_water_promo_5_plus_1())
