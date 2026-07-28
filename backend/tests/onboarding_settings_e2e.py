"""Venue onboarding settings and default reconciliation tolerance tests."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token


DSN = os.environ["TEST_DATABASE_DSN"]
results: list[str] = []
SUPPLIER_ORDER = str(uuid4())
ORDER = str(uuid4())


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    results.append(name)


def scalar(sql: str, args=()):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
            row = cursor.fetchone()
            return row[0] if row else None


def seed_order() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into liquidstock_supplier_orders(
                  liquidstock_order_id,liquidstock_supplier_order_id,
                  liquidstock_venue_id,venue_name_snapshot,
                  liquidstock_supplier_id,supplier_id,supplier_name_snapshot,
                  order_version,status,sent_at,requested_delivery_date,
                  last_event_id,created_at,updated_at
                ) values (
                  %s,%s,
                  (select liquidstock_venue_id from liquidstock_venue_mappings where location_id=1),
                  'Venue A',%s,1,'Supplier A',1,'confirmed',now(),
                  current_date,%s,now(),now()
                )
                """,
                (ORDER, SUPPLIER_ORDER, str(uuid4()), str(uuid4())),
            )


async def run() -> None:
    seed_order()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager_a = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    manager_b = {"Authorization": f"Bearer {create_access_token(3, 'manager')}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        response = await client.get(
            "/api/v1/onboarding/locations/1/readiness", headers=manager_a
        )
        check(
            "manager reads own location readiness",
            response.status_code == 200
            and response.json()["location_id"] == 1,
        )
        response = await client.get(
            "/api/v1/onboarding/locations/1/readiness", headers=manager_b
        )
        check("manager cross location blocked", response.status_code == 403)

        payload = {
            "price_tolerance_absolute": "0.25",
            "price_tolerance_percent": "2.5",
            "important_anomaly_threshold": "80",
            "stalled_reconciliation_days": 4,
            "missing_credit_note_days": 10,
            "notifications_enabled": True,
        }
        response = await client.put(
            "/api/v1/onboarding/locations/1/settings",
            headers=manager_a,
            json=payload,
        )
        check("manager cannot change settings", response.status_code == 403)
        response = await client.put(
            "/api/v1/onboarding/locations/1/settings",
            headers=admin,
            json=payload,
        )
        if response.status_code != 200:
            raise AssertionError(
                f"admin saves explicit location settings: "
                f"{response.status_code} {response.text}"
            )
        check(
            "admin saves explicit location settings",
            response.json()["configured"] is True
            and float(response.json()["price_tolerance_absolute"]) == 0.25,
        )

        response = await client.get(
            "/api/v1/onboarding/locations/1/settings", headers=manager_a
        )
        check(
            "manager reads configured settings",
            response.status_code == 200
            and float(response.json()["price_tolerance_percent"]) == 2.5,
        )

        response = await client.post(
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER}/invoice",
            headers=manager_a,
            json={"fattura_id": 1},
        )
        check(
            "reconciliation inherits location tolerances when omitted",
            response.status_code == 200
            and float(response.json()["price_tolerance_absolute"]) == 0.25
            and float(response.json()["price_tolerance_percent"]) == 2.5,
        )

        response = await client.get(
            "/api/v1/onboarding/locations/1/readiness", headers=admin
        )
        readiness = response.json()
        check(
            "readiness reflects operational data",
            response.status_code == 200
            and readiness["settings_configured"] is True
            and readiness["liquidstock_venue_mapped"] is True
            and readiness["invoices"] >= 1
            and readiness["reconciliations"] >= 1,
        )

    check(
        "settings are isolated by location",
        scalar(
            "select count(*) from location_reconciliation_settings "
            "where location_id=2"
        )
        == 0,
    )
    print(
        json.dumps(
            {"status": "PASS", "tests": len(results), "results": results},
            indent=2,
        )
    )


asyncio.run(run())
