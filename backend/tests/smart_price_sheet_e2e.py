"""Smart Price Sheet API test. Run only against a disposable migrated database."""

import asyncio
import json
import os

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token


DSN = os.environ["TEST_DATABASE_DSN"]
results: list[str] = []


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    results.append(name)


def scalar(sql: str):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()[0]


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into location(id,nome_struttura,piva_riferimento,tipologia)
                values (1,'Test Venue','00000000001','ristorante') on conflict do nothing;
                insert into utenti(id,email,password_hash,ruolo,location_id,attivo,refresh_token_version)
                values (1,'admin@test.local','x','admin',null,true,1),
                       (2,'manager@test.local','x','manager',1,true,1) on conflict do nothing;
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Supplier A',true),(2,'10000000002','Supplier B',true),
                       (3,'10000000003','Supplier C Unrelated',true)
                on conflict do nothing;
                insert into products(
                  id,sku_interno,canonical_name,normalized_name,category,comparison_unit,
                  is_commodity,is_active,unit_count,created_at,updated_at
                ) values (1,'WATER-75','Water 75cl','water 75cl','beverage','piece',false,true,1,now(),now())
                on conflict do nothing;
                insert into supplier_product_aliases(
                  id,supplier_id,product_id,supplier_code,raw_description,normalized_description,
                  status,confidence_score,source,first_seen_at,last_seen_at,created_at,updated_at
                ) values
                  (1,1,1,'A-WATER','Water A','water a','approved',1,'test',now(),now(),now(),now()),
                  (2,2,1,'B-WATER','Water B','water b','approved',1,'test',now(),now(),now(),now())
                on conflict do nothing;
                insert into listino_master(
                  id,fornitore_id,sku_interno,descrizione,prezzo_pattuito,unita_misura,
                  data_inizio_validita,supplier_product_alias_id
                ) values
                  (1,1,'WATER-75','Water A',9,'piece','2026-01-01',1),
                  (2,2,'WATER-75','Water B',10,'piece','2026-01-01',2)
                on conflict do nothing;
                select setval(pg_get_serial_sequence('listino_master','id'), 2, true);
                """
            )


async def run() -> None:
    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        response = await client.get("/api/v1/smart-price-sheet/matrix", headers=admin)
        matrix_row = response.json()["rows"][0]
        check("canonical matrix", response.status_code == 200 and response.json()["total"] == 1)
        check("unrelated supplier excluded", matrix_row["eligible_supplier_ids"] == [1, 2])
        response = await client.get(
            "/api/v1/smart-price-sheet/matrix?location_id=2", headers=manager
        )
        check("manager cross-location blocked", response.status_code == 403)

        before = scalar("select count(*) from listino_master")
        response = await client.post(
            "/api/v1/smart-price-sheet/preview",
            headers=admin,
            json={
                "text": "Prodotto\tSupplier A\nWater 75cl\t8,50",
                "effective_date": "2026-08-06",
                "default_uom": "piece",
            },
        )
        preview = response.json()
        check(
            "preview validated",
            response.status_code == 200
            and preview["can_commit"] is True
            and preview["counts"]["update"] == 1,
        )
        check("preview does not write prices", scalar("select count(*) from listino_master") == before)

        response = await client.post(
            "/api/v1/smart-price-sheet/preview",
            headers=admin,
            json={
                "text": "Prodotto\tSupplier C Unrelated\nWater 75cl\t7,00",
                "effective_date": "2026-08-06",
                "default_uom": "piece",
            },
        )
        check(
            "out-of-sector price blocked",
            response.status_code == 200
            and any(item["type"] == "supplier_scope" for item in response.json()["errors"]),
        )

        response = await client.post(
            "/api/v1/smart-price-sheet/commit",
            headers=admin,
            json={"preview_token": preview["preview_token"], "confirm": True},
        )
        check(
            "commit creates version",
            response.status_code == 200
            and response.json()["result"]["updated"] == 1
            and scalar("select count(*) from listino_master") == before + 1,
        )
        response = await client.post(
            "/api/v1/smart-price-sheet/commit",
            headers=admin,
            json={"preview_token": preview["preview_token"], "confirm": True},
        )
        check(
            "commit retry idempotent",
            response.status_code == 200 and scalar("select count(*) from listino_master") == before + 1,
        )

        response = await client.post(
            "/api/v1/smart-price-sheet/preview",
            headers=admin,
            json={
                "text": "Nome rapido ordine\tProdotto reale / SKU\nACQUA\tWater 75cl",
                "effective_date": "2026-08-06",
                "default_uom": "piece",
            },
        )
        name_preview = response.json()
        check(
            "optional order name preview",
            response.status_code == 200
            and name_preview["can_commit"] is True
            and name_preview["order_name_changes"][0]["new_order_name"] == "ACQUA",
        )
        response = await client.post(
            "/api/v1/smart-price-sheet/commit",
            headers=admin,
            json={"preview_token": name_preview["preview_token"], "confirm": True},
        )
        check(
            "optional order name committed",
            response.status_code == 200
            and response.json()["result"]["order_names_updated"] == 1,
        )

        response = await client.put(
            "/api/v1/smart-price-sheet/assessments",
            headers=admin,
            json={
                "product_id": 1,
                "supplier_id": 1,
                "status": "blocked",
                "quality_score": 2,
                "reason": "Repeated quality incident",
            },
        )
        check("blocked assessment audited", response.status_code == 200)
        response = await client.put(
            "/api/v1/smart-price-sheet/policies",
            headers=admin,
            json={
                "product_id": 1,
                "selection_mode": "best_eligible_price",
                "minimum_quality": 1,
                "max_price_premium_percent": "0",
                "max_price_premium_absolute": "0",
                "allow_spot": True,
            },
        )
        check("purchase policy audited", response.status_code == 200)
        response = await client.get("/api/v1/smart-price-sheet/matrix", headers=admin)
        row = response.json()["rows"][0]
        check(
            "cheapest and recommended are distinct",
            row["absolute_cheapest_supplier_id"] == 1
            and row["recommended_supplier_id"] == 2,
        )

        response = await client.post(
            "/api/v1/orders/resolve-item",
            headers=admin,
            json={"query": "WATER-75", "requested_qty": 1},
        )
        order_result = response.json()
        check(
            "order resolver consumes policy",
            response.status_code == 200
            and order_result["absolute_cheapest"]["supplier_id"] == 1
            and order_result["recommended_offer"]["supplier_id"] == 2
            and order_result["best_offer"]["supplier_id"] == 2,
        )
        response = await client.post(
            "/api/v1/orders/resolve-item",
            headers=admin,
            json={"query": "ACQUA", "requested_qty": 1},
        )
        check(
            "order resolver uses quick name",
            response.status_code == 200
            and response.json()["matched_product"]["sku_interno"] == "WATER-75",
        )
        with psycopg2.connect(DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into products(
                      id,sku_interno,canonical_name,normalized_name,order_name,
                      normalized_order_name,category,comparison_unit,is_commodity,
                      is_active,unit_count,created_at,updated_at
                    ) values (
                      2,'SOAP-TEST','Soap test','soap test','Water 75cl',
                      'water 75cl','cleaning','piece',false,true,1,now(),now()
                    )
                    """
                )
        response = await client.post(
            "/api/v1/orders/resolve-item",
            headers=admin,
            json={"query": "Water 75cl", "requested_qty": 1},
        )
        check(
            "real invoice name wins over quick name",
            response.status_code == 200
            and response.json()["matched_product"]["sku_interno"] == "WATER-75",
        )

        deviation = {
            "dedupe_key": "smart-test-order-1-product-1",
            "product_id": 1,
            "location_id": 1,
            "recommended_supplier_id": 2,
            "selected_supplier_id": 1,
            "deviation_type": "blocked_supplier",
            "reason": "Explicit test override",
        }
        first = await client.post(
            "/api/v1/smart-price-sheet/deviations", headers=admin, json=deviation
        )
        second = await client.post(
            "/api/v1/smart-price-sheet/deviations", headers=admin, json=deviation
        )
        check(
            "policy deviation idempotent",
            first.status_code == 200
            and first.json()["created"] is True
            and second.json()["created"] is False,
        )
        deviation_id = first.json()["id"]
        response = await client.patch(
            f"/api/v1/smart-price-sheet/deviations/{deviation_id}",
            headers=manager,
            json={"status": "acknowledged"},
        )
        check(
            "manager acknowledges own-location deviation",
            response.status_code == 200
            and response.json()["status"] == "acknowledged"
            and response.json()["acknowledged_by"] == 2,
        )
        check(
            "audit rows persisted",
            scalar("select count(*) from product_supplier_assessment_audits") == 1
            and scalar("select count(*) from product_purchase_policy_audits") == 1,
        )

    print(json.dumps({"status": "PASS", "tests": len(results), "results": results}, indent=2))


asyncio.run(run())
