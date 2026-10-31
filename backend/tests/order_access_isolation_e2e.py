"""Adversarial RBAC/tenant test for order APIs, on disposable GitHub Postgres only.

No external orders are sent: tests call the FastAPI ASGI app in-process.
Real V1 and shared V2 staging databases must never be used.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token

DSN = os.environ["TEST_DATABASE_DSN"]


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}", flush=True)


def scalar(sql: str):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()[0]


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id,nome_struttura,piva_riferimento,tipologia,tenant_id)
                values
                    (1,'Synthetic venue tenant A','00000000001','ristorante',1),
                    (2,'Synthetic venue tenant B','00000000002','ristorante',2);
                insert into utenti(id,email,password_hash,ruolo,ruolo_dettagliato,
                                   location_id,tenant_id,attivo,settore_abilitato,refresh_token_version)
                values
                    (1,'admin.a@test.local','x','admin','admin',null,1,true,'all',1),
                    (2,'manager.a@test.local','x','manager','admin',1,1,true,'Food',1),
                    (3,'admin.b@test.local','x','admin','admin',null,2,true,'all',1),
                    (4,'manager.b@test.local','x','manager','admin',2,2,true,'Food',1),
                    (5,'unassigned.a@test.local','x','manager','admin',null,1,true,'all',1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Supplier CI synthetic',true);
                insert into products(
                    id,sku_interno,canonical_name,normalized_name,category,comparison_unit,
                    is_commodity,is_active,unit_count,created_at,updated_at)
                values (1,'CI-SKU','Synthetic food','synthetic food','Food','piece',
                        false,true,1,now(),now());
                insert into listino_master(id,fornitore_id,sku_interno,descrizione,
                    prezzo_pattuito,unita_misura,data_inizio_validita)
                values (1,1,'CI-SKU','Synthetic food',4,'pz','2026-01-01');
                insert into ordini(
                    id,fornitore_id,location_id,user_id,tenant_id,settore,data_ordine,
                    spesa_totale,stato,stato_ricezione)
                values
                    (101,1,1,2,1,'Food',now(),8,'inviato','da_ricevere'),
                    (202,1,2,4,2,'Food',now(),9,'inviato','da_ricevere');
                insert into righe_ordine(
                    id,ordine_id,product_id,sku_interno,descrizione,quantita,prezzo_pattuito,
                    prezzo_inserito,stato_ottimizzazione,stato_riga)
                values
                    (1011,101,1,'CI-SKU','Synthetic food',2,4,4,'concordato','in_attesa'),
                    (2022,202,1,'CI-SKU','Synthetic food',3,3,3,'concordato','in_attesa');
            """)


async def run() -> None:
    seed()
    admin_a = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager_a = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    admin_b = {"Authorization": f"Bearer {create_access_token(3, 'admin')}"}
    manager_b = {"Authorization": f"Bearer {create_access_token(4, 'manager')}"}
    unassigned = {"Authorization": f"Bearer {create_access_token(5, 'manager')}"}
    invalid_cross = {"location_id": 2, "settore": "Food", "items": [
        {"product_id": 1, "canonical_name": "Synthetic food", "quantita": 1}
    ]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver", timeout=15
    ) as client:
        for actor, headers, expected in (
            ("admin tenant A", admin_a, 101),
            ("manager tenant A with fake detailed admin role", manager_a, 101),
            ("admin tenant B", admin_b, 202),
            ("manager tenant B", manager_b, 202),
        ):
            r = await client.get("/api/v1/ordini/", headers=headers)
            check(f"{actor}: register has only permitted orders",
                  r.status_code == 200 and {row["id"] for row in r.json()} == {expected})
            r = await client.get("/api/v1/ordini/notifications/feed", headers=headers)
            check(f"{actor}: notifications isolated",
                  r.status_code == 200 and {row["id"] for row in r.json()["notifications"]} == {expected})

        r = await client.get("/api/v1/ordini/", headers=unassigned)
        check("unassigned manager cannot enumerate all locations", r.status_code == 403)

        for headers, denied in ((admin_a, 202), (manager_a, 202), (admin_b, 101), (manager_b, 101)):
            r = await client.get(f"/api/v1/ordini/{denied}", headers=headers)
            check("cross-tenant order detail denied", r.status_code == 403)
            r = await client.post(
                f"/api/v1/ordini/{denied}/ricezione", headers=headers,
                json={"stato_ricezione": "ricevuto_conforme", "righe": [
                    {"riga_id": 2022 if denied == 202 else 1011, "quantita_ricevuta": 1}
                ]},
            )
            check("cross-tenant order receipt denied", r.status_code == 403)

        r = await client.get("/api/v1/ordini/101", headers=unassigned)
        check("unassigned manager cannot open orders", r.status_code == 403)

        for headers in (admin_a, manager_a):
            r = await client.post("/api/v1/ordini/settore/elabora", headers=headers, json=invalid_cross)
            check("draft cannot access another tenant's venue", r.status_code == 403)
            r = await client.post(
                "/api/v1/ordini/settore/salva", headers=headers,
                json={"location_id": 2, "settore": "Food", "bundles": []},
            )
            check("save cannot target another tenant's venue", r.status_code == 403)

        r = await client.post(
            "/api/v1/ordini/settore/elabora", headers=manager_a,
            json={**invalid_cross, "location_id": 1, "settore": "Beverage"},
        )
        check("manager's unauthorized sector denied", r.status_code == 403)
        r = await client.post(
            "/api/v1/ordini/settore/elabora", headers=manager_a,
            json={**invalid_cross, "location_id": 1},
        )
        check("manager can draft within own venue and sector", r.status_code == 200)
        bundle = r.json()["fornitori_ordini"][0]
        save_payload = {"location_id": 1, "settore": "Food", "bundles": [bundle]}
        check("server draft uses agreed supplier contract",
              bundle["fornitore_id"] == 1
              and bundle["items"][0]["is_concordato"]
              and bundle["items"][0]["prezzo_unitario"] == 4)

        altered_total = copy.deepcopy(save_payload)
        altered_total["bundles"][0]["totale_ordine"] += 900
        r = await client.post("/api/v1/ordini/settore/salva", headers=manager_a,
                              json=altered_total)
        check("browser-forged purchase total rejected without inserts",
              r.status_code == 422 and scalar("select count(*) from ordini") == 2)

        altered_price = copy.deepcopy(save_payload)
        altered_price["bundles"][0]["items"][0]["prezzo_unitario"] = 1
        altered_price["bundles"][0]["items"][0]["subtotale"] = bundle["items"][0]["quantita"]
        altered_price["bundles"][0]["totale_ordine"] = bundle["items"][0]["quantita"]
        r = await client.post("/api/v1/ordini/settore/salva", headers=manager_a,
                              json=altered_price)
        check("browser-forged agreed price rejected without inserts",
              r.status_code == 422 and scalar("select count(*) from ordini") == 2)

        altered_name = copy.deepcopy(save_payload)
        altered_name["bundles"][0]["items"][0]["nome_prodotto"] = "Falso prodotto"
        r = await client.post("/api/v1/ordini/settore/salva", headers=manager_a,
                              json=altered_name)
        check("browser-forged canonical item name rejected", r.status_code == 422)

        forged_msg = copy.deepcopy(save_payload)
        forged_msg["bundles"][0]["whatsapp_message"] = "FAKE-TRANSFER-SYNTHETIC"
        r = await client.post("/api/v1/ordini/settore/salva", headers=manager_a,
                              json=forged_msg)
        check("genuine draft saved for own tenant", r.status_code == 200)
        check("supplier-facing text regenerated on server, not trusted from browser",
              "FAKE-TRANSFER-SYNTHETIC" not in scalar(
                  "select whatsapp_message from ordini where user_id=2 and id not in (101,202) limit 1"
              ))
        check("saved draft owner and tenant retained",
              scalar("select count(*) from ordini where user_id=2 and tenant_id=1") == 2)

        r = await client.post(
            "/api/v1/ordini/crea", headers=admin_a,
            json={"location_id": 2, "items": [{"sku_interno": "CI-SKU", "quantita": 1}]},
        )
        check("admin cannot create order in a different tenant", r.status_code == 403)
        r = await client.post(
            "/api/v1/ordini/crea", headers=admin_a,
            json={"location_id": 1, "items": [{"sku_interno": "CI-SKU", "quantita": 1}]},
        )
        check("admin can save own tenant order", r.status_code == 200 and len(r.json()) == 1)
        check("new order retains caller's tenant and user",
              scalar("select count(*) from ordini where tenant_id=1 and user_id=1") == 1)

        bad_line = [
            {"riga_id": 1011, "quantita_ricevuta": 3, "stato_riga": "conforme"}
        ]
        r = await client.post(
            "/api/v1/ordini/101/ricezione", headers=manager_a,
            json={"stato_ricezione": "ricevuto_conforme", "righe": bad_line},
        )
        check("receiving more than ordered fails without DB writes",
              r.status_code == 422
              and scalar("select quantita_ricevuta is null from righe_ordine where id=1011"))

        for entries in (
            [{"riga_id": 9999, "quantita_ricevuta": 1}],
            [{"riga_id": 1011, "quantita_ricevuta": 1},
             {"riga_id": 1011, "quantita_ricevuta": 1}],
            [],
        ):
            r = await client.post(
                "/api/v1/ordini/101/ricezione", headers=manager_a,
                json={"stato_ricezione": "ricevuto_parziale", "righe": entries},
            )
            check("missing/foreign/repeated order line rejected", r.status_code == 422)

        r = await client.post(
            "/api/v1/ordini/101/ricezione", headers=manager_a,
            json={"stato_ricezione": "ricevuto_conforme",
                  "righe": [{"riga_id": 1011, "quantita_ricevuta": 2, "stato_riga": "conforme"}]},
        )
        check("legitimate manager can confirm receiving own order",
              r.status_code == 200 and r.json()["stato_ricezione"] == "ricevuto_conforme")
        check("received quantity stored accurately",
              scalar("select quantita_ricevuta from righe_ordine where id=1011") == 2)

        r = await client.get("/api/v1/ordini/101", headers=manager_a)
        check("receipt reflected in authorized order detail",
              r.status_code == 200 and r.json()["righe"][0]["quantita_ricevuta"] == 2)
        check("tenant B order unchanged", scalar("select stato_ricezione from ordini where id=202") == "da_ricevere")

    print(json.dumps({"status": "PASS", "scope": "effective RBAC, tenant and venue guard, order receipt"}, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
