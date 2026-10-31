"""E2E tests for supplier price forms on a disposable CI database only.

Covers the public no-login flow and asserts that a submitted offer does not
write to the official supplier price list.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token

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
            """)


async def run() -> None:
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
        rows = [{
            "product_id": 1, "supplier_id": 1, "sku": "CI-SKU-FORM",
            "offer_id": offer["id_offerta"], "description": offer["dicitura_fornitore"],
            "brand": offer["marca"], "quantity": offer["quantita_confezione"],
            "unit": offer["unita_misura"], "price": offer["prezzo"],
            "package_confirmed": True,
        } for offer in offers]
        preview = await client.post("/api/v1/smart-price-sheet/variant-preview",
                                    headers=admin_headers, json={"rows": rows})
        check("two variants have a reviewable price preview", preview.status_code == 200 and
              preview.json()["can_commit"] and preview.json()["counts"]["create"] == 2)
        token = preview.json()["preview_token"]
        commit = await client.post("/api/v1/smart-price-sheet/commit", headers=admin_headers,
                                   json={"preview_token": token, "confirm": True})
        check("admin imports both variants as separate contracts", commit.status_code == 200 and
              commit.json()["result"]["created"] == 2)
        repeat = await client.post("/api/v1/smart-price-sheet/commit", headers=admin_headers,
                                   json={"preview_token": token, "confirm": True})
        check("retry does not duplicate either price", repeat.status_code == 200 and
              repeat.json()["result"] == commit.json()["result"])
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


if __name__ == "__main__":
    asyncio.run(run())
