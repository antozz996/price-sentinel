"""E2E tests for supplier price forms on a disposable CI database only.

Covers the public no-login flow and asserts that a submitted offer does not
write to the official supplier price list.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from decimal import Decimal

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token
from app.services.variant_price_import import _dimensions

DSN = os.environ["TEST_DATABASE_DSN"]


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id,nome_struttura,piva_riferimento,tipologia,tenant_id)
                values (1,'Supplier forms CI venue','00000000001','ristorante',1);
                insert into utenti(id,email,password_hash,ruolo,ruolo_dettagliato,
                                   location_id,tenant_id,attivo,settore_abilitato,
                                   refresh_token_version)
                values (1,'supplier-forms-admin@test.local','x','admin','admin',
                        null,1,true,'all',1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Supplier forms CI synthetic',true);
                insert into products(
                    id,sku_interno,canonical_name,normalized_name,category,
                    comparison_unit,is_commodity,is_active,unit_count,created_at,updated_at)
                values (1,'CI-SKU-FORM','Synthetic beverage','synthetic beverage',
                        'Beverage','BT',false,true,1,now(),now());
                -- Explicit ids above do not advance the sequences used by the API.
                select setval(pg_get_serial_sequence('fornitori','id'), (select max(id) from fornitori));
            """)


async def run() -> None:
    check("preset KG is converted after canonical normalization",
          _dimensions(Decimal("2.8"), "KG") == (1, None, 2800))
    check("preset CL is converted after canonical normalization",
          _dimensions(Decimal("75"), "CL") == (1, 750, None))
    check("preset package units remain countable",
          _dimensions(Decimal("6"), "CT") == (6, None, None))
    seed()
    admin_headers = {
        "Authorization": f"Bearer {create_access_token(1, 'admin')}"
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        timeout=15,
    ) as client:
        created = await client.post(
            "/api/v1/supplier-price-forms/",
            headers=admin_headers,
            json={
                "supplier_id": 1,
                "request_type": "new_listino",
                "category": "Beverage",
                "product_ids": [1],
                "expires_in_days": 14,
                "note": "Synthetic CI test",
            },
        )
        check("admin creates a new-listino form", created.status_code == 201)
        created_data = created.json()
        token = created_data["token"]
        item_id = created_data["request"]["items"][0]["id"]

        public_form = await client.get(
            f"/api/v1/supplier-price-forms/public/{token}"
        )
        check("supplier opens the token link without an account", public_form.status_code == 200)
        check(
            "public form exposes only the requested product",
            [item["id"] for item in public_form.json()["items"]] == [item_id],
        )

        start = date.today()
        end = start + timedelta(days=30)
        incomplete = await client.post(
            f"/api/v1/supplier-price-forms/public/{token}/submit",
            json={"validita_inviata_da": start.isoformat(), "answers": [{
                "item_id": item_id, "prezzo": "4.2500", "marca": "Marca sintetica CI",
                "unita_misura": "BT", "non_trattato": False,
            }]},
        )
        check("incomplete supplier packaging cannot be submitted", incomplete.status_code == 422)
        submitted = await client.post(
            f"/api/v1/supplier-price-forms/public/{token}/submit",
            json={
                "validita_inviata_da": start.isoformat(),
                "validita_inviata_a": end.isoformat(),
                "answers": [{
                    "item_id": item_id,
                    "prezzo": "4.2500",
                    "marca": "Marca sintetica CI",
                    "dicitura_fornitore": "Bottiglia sintetica CI",
                    "quantita_confezione": "1.000",
                    "unita_misura": "BT",
                    "conferma_prezzo": False,
                    "non_trattato": False,
                    "nota": "Synthetic offer",
                    "offerte": [
                        {"prezzo": "4.2500", "marca": "Marca sintetica CI",
                         "dicitura_fornitore": "Bottiglia sintetica CI", "quantita_confezione": "1.000",
                         "unita_misura": "BT"},
                        {"prezzo": "7.9500", "marca": "Seconda marca CI",
                         "dicitura_fornitore": "Bottiglie sintetiche CI in coppia", "quantita_confezione": "2.000",
                         "unita_misura": "BT"},
                    ],
                }],
            },
        )
        check("supplier submits the new offer without login", submitted.status_code == 200)

        replay = await client.get(
            f"/api/v1/supplier-price-forms/public/{token}"
        )
        check("submitted link cannot be reused", replay.status_code == 404)

        detail = await client.get(
            f"/api/v1/supplier-price-forms/{created_data['request']['id']}",
            headers=admin_headers,
        )
        check("admin can review the submitted proposal", detail.status_code == 200)
        reviewed = detail.json()
        check("submission remains a proposal awaiting review", reviewed["status"] == "submitted")
        offers = reviewed["items"][0]["offerte_inviate"]
        check("two distinct packages are retained", len(offers) == 2 and
              len({offer["id_offerta"] for offer in offers}) == 2)
        check(
            "submitted price and validity are retained",
            reviewed["items"][0]["prezzo_inviato"] == "4.2500"
            and reviewed["items"][0]["brand_inviata"] == "Marca sintetica CI"
            and reviewed["items"][0]["dicitura_inviata"] == "Bottiglia sintetica CI"
            and reviewed["items"][0]["quantita_inviata"] == "1.000"
            and reviewed["validita_inviata_da"] == start.isoformat()
            and reviewed["validita_inviata_a"] == end.isoformat(),
        )

    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from listino_master "
                "where fornitore_id=%s and sku_interno=%s",
                (1, "CI-SKU-FORM"),
            )
            official_rows = cursor.fetchone()[0]
    check("supplier submission never changes the official price list", official_rows == 0)

    # The following is an explicit admin import on this CI-only disposable DB.
    # No Google Sheet or live service is contacted.
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into supplier_category_capabilities
                    (supplier_id, category, enabled, reason, created_by, updated_by, created_at, updated_at)
                values (1, 'Beverage', true, 'Synthetic CI approval', 1, 1, now(), now())
            """)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        pending = await client.get("/api/v1/supplier-price-forms/notifications/pending",
                                   headers=admin_headers)
        check("admin receives one pending supplier-response notification",
              pending.status_code == 200 and pending.json()["pending_count"] == 1)
        approval = await client.post(
            f"/api/v1/supplier-price-forms/{created_data['request']['id']}/approve",
            headers=admin_headers,
        )
        check("admin integrates both variants directly in V2 without a Sheet",
              approval.status_code == 200 and approval.json()["status"] == "approved" and
              approval.json()["result"]["created"] == 2)
        repeat = await client.post(
            f"/api/v1/supplier-price-forms/{created_data['request']['id']}/approve",
            headers=admin_headers,
        )
        check("a reviewed response cannot be applied twice", repeat.status_code == 409)
        pending_after = await client.get("/api/v1/supplier-price-forms/notifications/pending",
                                         headers=admin_headers)
        check("notification clears after approval",
              pending_after.status_code == 200 and pending_after.json()["pending_count"] == 0)
        resolved = await client.post("/api/v1/product-identity/orders/resolve-item", headers=admin_headers,
                                     json={"query": "CI-SKU-FORM", "requested_qty": 2})
        check("both formats remain separate in order suggestions", resolved.status_code == 200 and
              len(resolved.json().get("alternatives", [])) == 1)
        draft = await client.post("/api/v1/ordini/settore/elabora", headers=admin_headers, json={
            "location_id": 1, "settore": "Beverage", "items": [{
                "product_id": 1, "sku_interno": "CI-SKU-FORM", "canonical_name": "Synthetic beverage",
                "quantita": 2, "comparison_unit": "conf", "preferred_supplier_id": 1,
                "preferred_offer_id": offers[1]["id_offerta"],
            }],
        })
        check("buyer can explicitly choose the second format", draft.status_code == 200 and
              draft.json()["fornitori_ordini"][0]["items"][0]["prezzo_unitario"] == 7.95 and
              "Seconda marca CI" in draft.json()["fornitori_ordini"][0]["whatsapp_message"])
        order = await client.post("/api/v1/ordini/settore/salva", headers=admin_headers, json={
            "location_id": 1, "settore": "Beverage",
            "bundles": draft.json()["fornitori_ordini"],
        })
        check("chosen format and price survive order validation", order.status_code == 200)

        # Next round: a confirmation form from the catalog. A row from an older import
        # must not be re-asked, offers show their real format (not "conf"), and
        # approving the response closes the older row it replaces.
        with psycopg2.connect(DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("insert into listino_master(fornitore_id,sku_interno,descrizione,prezzo_pattuito,"
                               "data_inizio_validita) values (1,'CI-SKU-FORM','Synthetic beverage',9.99,%s) "
                               "returning id", (start - timedelta(days=10),))
                legacy_id = cursor.fetchone()[0]
        catalog = await client.get("/api/v1/supplier-price-forms/catalog/1", headers=admin_headers)
        catalog_rows = [row for row in catalog.json() if row["sku_interno"] == "CI-SKU-FORM"]
        check("catalog shows only the approved offers with their real format",
              catalog.status_code == 200
              and sorted(row["unita_misura"] for row in catalog_rows) == ["2 BT", "BT"]
              and legacy_id not in [row["id"] for row in catalog_rows])
        confirmation = await client.post("/api/v1/supplier-price-forms/", headers=admin_headers, json={
            "supplier_id": 1, "request_type": "confirmation",
            "listino_ids": [row["id"] for row in catalog_rows] + [legacy_id]})
        check("admin creates a confirmation form", confirmation.status_code == 201)
        confirmation_token = confirmation.json()["token"]
        confirmation_items = (await client.get(
            f"/api/v1/supplier-price-forms/public/{confirmation_token}")).json()["items"]
        offer_items = [item for item in confirmation_items if item["quantita_corrente"]]
        legacy_item = next(item for item in confirmation_items if not item["quantita_corrente"])
        check("confirmation form carries quantity, unit and wording of each offer",
              sorted((i["quantita_corrente"], i["unita_corrente"], i["dicitura_corrente"]) for i in offer_items)
              == [("1.000", "BT", "Bottiglia sintetica CI"), ("2.000", "BT", "Bottiglie sintetiche CI in coppia")])
        check("a row without a known format asks for the unit", legacy_item["unita_corrente"] is None)

        def confirm_all(quantity_override: str | None) -> dict:
            answers = [{"item_id": item["id"], "non_trattato": False, "offerte": [{
                "prezzo": item["prezzo_corrente"], "unita_misura": item["unita_corrente"],
                "marca": item["brand_corrente"], "dicitura_fornitore": item["dicitura_corrente"],
                "quantita_confezione": quantity_override or item["quantita_corrente"],
                "conferma_prezzo": True}]} for item in offer_items]
            answers.append({"item_id": legacy_item["id"], "non_trattato": False, "offerte": [{
                "prezzo": "20.0000", "unita_misura": "BT", "dicitura_fornitore": "Cassa sintetica CI da 6",
                "quantita_confezione": "6"}]})
            return {"validita_inviata_da": start.isoformat(), "answers": answers}

        wrong_quantity = await client.post(
            f"/api/v1/supplier-price-forms/public/{confirmation_token}/submit", json=confirm_all("3"))
        check("a confirmation with a different quantity is refused", wrong_quantity.status_code == 422)
        confirmed = await client.post(
            f"/api/v1/supplier-price-forms/public/{confirmation_token}/submit", json=confirm_all(None))
        check("supplier confirms the agreed offers as prefilled", confirmed.status_code == 200)
        confirmation_approval = await client.post(
            f"/api/v1/supplier-price-forms/{confirmation.json()['request']['id']}/approve", headers=admin_headers)
        check("approval keeps confirmed offers and adds the new one",
              confirmation_approval.status_code == 200
              and confirmation_approval.json()["result"]["created"] == 1
              and confirmation_approval.json()["result"]["unchanged"] == 2)
        with psycopg2.connect(DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select data_scadenza from listino_master where id=%s", (legacy_id,))
                legacy_end = cursor.fetchone()[0]
                cursor.execute("select count(*) from listino_master where fornitore_id=1 and sku_interno='CI-SKU-FORM' "
                               "and supplier_product_alias_id is not null and (data_scadenza is null or data_scadenza>=%s)",
                               (start,))
                open_offers = cursor.fetchone()[0]
        check("the replaced older row is closed the day before the new validity",
              legacy_end == start - timedelta(days=1))
        check("confirmed and new offers stay active", open_offers == 3)

        delete_approved = await client.delete(
            f"/api/v1/supplier-price-forms/{created_data['request']['id']}", headers=admin_headers)
        check("an approved response cannot be deleted (audit trail)", delete_approved.status_code == 409)

        overdue = await client.post("/api/v1/supplier-price-forms/", headers=admin_headers, json={
            "supplier_id": 1, "request_type": "new_listino", "category": "Beverage",
            "product_ids": [1], "expires_in_days": 1,
        })
        check("admin creates a second form", overdue.status_code == 201)
        overdue_id = overdue.json()["request"]["id"]
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("update supplier_price_form_requests set expires_at=now() - interval '1 minute' "
                           "where id=%s", (overdue_id,))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        expired = await client.get("/api/v1/supplier-price-forms/?status_filter=expired", headers=admin_headers)
        check("an overdue link is listed under the expired filter",
              expired.status_code == 200 and [f["id"] for f in expired.json()] == [overdue_id])
        still_open = await client.get("/api/v1/supplier-price-forms/?status_filter=open", headers=admin_headers)
        check("an overdue link is not listed as open",
              still_open.status_code == 200 and overdue_id not in [f["id"] for f in still_open.json()])
        delete_expired = await client.delete(f"/api/v1/supplier-price-forms/{overdue_id}", headers=admin_headers)
        check("a non-approved form can still be deleted", delete_expired.status_code == 200)

        # New supplier invited from the forms page with a provisional name.
        new_supplier = await client.post("/api/v1/supplier-price-forms/new-supplier", headers=admin_headers,
                                         json={"nome": "Fornitore da invitare CI", "categories": ["Beverage"]})
        check("admin creates a provisional supplier", new_supplier.status_code == 201)
        new_id = new_supplier.json()["id"]
        duplicate = await client.post("/api/v1/supplier-price-forms/new-supplier", headers=admin_headers,
                                      json={"nome": "fornitore da invitare ci", "categories": ["Beverage"]})
        check("the same provisional name cannot be created twice", duplicate.status_code == 409)

        async def invite() -> tuple[int, str, int]:
            made = await client.post("/api/v1/supplier-price-forms/", headers=admin_headers, json={
                "supplier_id": new_id, "request_type": "new_listino", "category": "Beverage", "product_ids": [1]})
            body = made.json()
            return body["request"]["id"], body["token"], body["request"]["items"][0]["id"]

        def answer(item: int, details: dict | None) -> dict:
            payload = {"validita_inviata_da": date.today().isoformat(), "answers": [{
                "item_id": item, "non_trattato": False, "offerte": [{
                    "prezzo": "3.9000", "marca": "Marca nuova CI", "dicitura_fornitore": "Bottiglia nuova CI",
                    "quantita_confezione": "1.000", "unita_misura": "BT"}]}]}
            if details is not None:
                payload["anagrafica"] = details
            return payload

        req_id, token, item = await invite()
        public = await client.get(f"/api/v1/supplier-price-forms/public/{token}")
        check("the new supplier's form asks for company details",
              public.status_code == 200 and public.json()["requires_supplier_details"] is True)
        missing = await client.post(f"/api/v1/supplier-price-forms/public/{token}/submit", json=answer(item, None))
        check("company details are required for a new supplier", missing.status_code == 422)
        bad_vat = await client.post(f"/api/v1/supplier-price-forms/public/{token}/submit", json=answer(item, {
            "ragione_sociale": "Nuova Bevande CI Srl", "partita_iva": "1234", "telefono_ordini": "333 1234567"}))
        check("an invalid VAT number is refused", bad_vat.status_code == 422)
        clash = await client.post(f"/api/v1/supplier-price-forms/public/{token}/submit", json=answer(item, {
            "ragione_sociale": "Nuova Bevande CI Srl", "partita_iva": "IT 10000000001", "telefono_ordini": "333 1234567"}))
        check("the supplier submits company details", clash.status_code == 200)
        clash_approval = await client.post(f"/api/v1/supplier-price-forms/{req_id}/approve", headers=admin_headers)
        check("approval stops when the VAT number belongs to another supplier", clash_approval.status_code == 409)
        await client.post(f"/api/v1/supplier-price-forms/{req_id}/reject", headers=admin_headers)

        req_id, token, item = await invite()
        sent = await client.post(f"/api/v1/supplier-price-forms/public/{token}/submit", json=answer(item, {
            "ragione_sociale": "Nuova Bevande CI Srl", "partita_iva": "20000000002", "telefono_ordini": "+39 333 1234567"}))
        check("the corrected response is submitted", sent.status_code == 200)
        review = await client.get(f"/api/v1/supplier-price-forms/{req_id}", headers=admin_headers)
        check("admin sees the submitted company details",
              review.json()["anagrafica_inviata"] == {"ragione_sociale": "Nuova Bevande CI Srl",
                                                     "partita_iva": "20000000002",
                                                     "telefono_ordini": "+39 333 1234567"})
        approved_new = await client.post(f"/api/v1/supplier-price-forms/{req_id}/approve", headers=admin_headers)
        check("the new supplier's offer is approved", approved_new.status_code == 200)

    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select nome_azienda, partita_iva, telefono_contatto from fornitori where id=%s", (new_id,))
            check("approval writes the company details on the supplier record",
                  cursor.fetchone() == ("Nuova Bevande CI Srl", "20000000002", "+39 333 1234567"))


if __name__ == "__main__":
    asyncio.run(run())
