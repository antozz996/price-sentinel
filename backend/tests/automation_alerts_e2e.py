"""Automation alerts are idempotent, scoped and never make economic decisions."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token


DSN = os.environ[
    "TEST_DATABASE_DSN"
]
results: list[str] = []
RECONCILIATION = str(uuid4())
SUPPLIER_ORDER = str(uuid4())
ORDER = str(uuid4())


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    results.append(name)


def execute(sql: str, args=()) -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)


def scalar(sql: str, args=()):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchone()[0]


def seed_conditions() -> str:
    case_id = scalar(
        "select id from dispute_cases where status <> 'closed' order by created_at limit 1"
    )
    execute(
        """
        insert into purchase_order_reconciliations(
          id,liquidstock_supplier_order_id,liquidstock_order_id,supplier_id,
          venue_id,status,matching_confidence,reconciliation_version,
          price_tolerance_absolute,price_tolerance_percent,created_at,updated_at
        ) values (
          %s,%s,%s,1,
          (select liquidstock_venue_id from liquidstock_venue_mappings where location_id=1),
          'awaiting_invoice',0,1,.01,1,
          now()-interval '9 days',now()-interval '5 days'
        );

        insert into purchase_order_reconciliation_anomalies(
          reconciliation_id,liquidstock_supplier_order_id,supplier_id,venue_id,
          anomaly_type,disputed_amount,evidence_key,evidence,workflow_status,
          created_at,updated_at
        ) values (
          %s,%s,1,
          (select liquidstock_venue_id from liquidstock_venue_mappings where location_id=1),
          'price_overcharge',75,'automation-important',
          '{"description":"High impact test"}','contestata',now(),now()
        );

        insert into liquidstock_integration_events(
          source,external_event_id,event_type,integration_version,payload,
          payload_hash,received_at,processing_status,processing_error,created_at
        ) values (
          'liquidstock',%s,'supplier_order_received','1.0','{}',
          repeat('a',64),now(),'failed','projection_failure',now()
        );

        update dispute_case_anomalies
        set recognized_amount=claimed_amount
        where dispute_case_id=%s;

        update dispute_cases
        set status='credit_note_expected',
            recognized_amount=requested_amount,
            due_date=current_date,
            updated_at=now()-interval '8 days'
        where id=%s;
        """,
        (
            RECONCILIATION,
            SUPPLIER_ORDER,
            ORDER,
            RECONCILIATION,
            SUPPLIER_ORDER,
            str(uuid4()),
            case_id,
            case_id,
        ),
    )
    return str(case_id)


async def run() -> None:
    case_id = seed_conditions()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager_a = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    manager_b = {"Authorization": f"Bearer {create_access_token(3, 'manager')}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        response = await client.post("/api/v1/automation/run", headers=manager_a)
        check("only admin can run monitor", response.status_code == 403)

        response = await client.post("/api/v1/automation/run", headers=admin)
        check(
            "monitor detects operational conditions",
            response.status_code == 200
            and response.json()["status"] == "completed"
            and response.json()["alerts_detected"] >= 6,
        )

        response = await client.get("/api/v1/automation/alerts", headers=admin)
        alerts = response.json()
        types = {item["alert_type"] for item in alerts if item["status"] != "resolved"}
        check(
            "all required alert families generated",
            {
                "reconciliation_stalled",
                "invoice_candidate_available",
                "important_anomaly",
                "dispute_due",
                "credit_note_missing",
                "integration_event_failed",
            }.issubset(types),
        )

        response = await client.get(
            "/api/v1/automation/alerts", headers=manager_a
        )
        manager_alerts = response.json()
        check(
            "manager sees only own venue alerts",
            response.status_code == 200
            and manager_alerts
            and all(item["location_id"] == 1 for item in manager_alerts),
        )
        response = await client.get(
            "/api/v1/automation/alerts", headers=manager_b
        )
        check(
            "other venue cannot see alerts",
            response.status_code == 200 and response.json() == [],
        )

        location_alert = next(
            item for item in alerts if item["location_id"] == 1
        )
        response = await client.post(
            f"/api/v1/automation/alerts/{location_alert['id']}/acknowledge",
            headers=manager_b,
        )
        check("cross venue acknowledge blocked", response.status_code == 403)
        response = await client.post(
            f"/api/v1/automation/alerts/{location_alert['id']}/acknowledge",
            headers=manager_a,
        )
        check(
            "own venue alert acknowledged",
            response.status_code == 200
            and response.json()["status"] == "acknowledged",
        )

        response = await client.post("/api/v1/automation/run", headers=admin)
        check(
            "second run is idempotent",
            response.status_code == 200
            and response.json()["alerts_created"] == 0,
        )
        check(
            "dedupe key remains unique",
            scalar(
                "select count(*) from (select dedupe_key from automation_alerts "
                "group by dedupe_key having count(*)>1) duplicated"
            )
            == 0,
        )

        before_fingerprint = scalar(
            "select coalesce(string_agg(id::text||':'||coalesce(fattura_id::text,''),"
            "'|' order by id),'') from purchase_order_reconciliations"
        )
        response = await client.get(
            f"/api/v1/disputes/{case_id}", headers=manager_a
        )
        check(
            "monitor did not mutate dispute economics",
            response.status_code == 200
            and response.json()["recovered_amount"] == "0.000000",
        )
        after_fingerprint = scalar(
            "select coalesce(string_agg(id::text||':'||coalesce(fattura_id::text,''),"
            "'|' order by id),'') from purchase_order_reconciliations"
        )
        check(
            "monitor never associates invoices",
            before_fingerprint == after_fingerprint,
        )

        execute(
            """
            update purchase_order_reconciliations
            set status='matched',updated_at=now()
            where id=%s;
            update purchase_order_reconciliation_anomalies
            set workflow_status='risolta',updated_at=now()
            where reconciliation_id=%s;
            update dispute_cases
            set status='closed',
                manual_close_reason='Closed after automation test',
                updated_at=now()
            where id=%s;
            update liquidstock_integration_events
            set processing_status='processed',
                processing_error=null,
                processed_at=now()
            where processing_status='failed';
            """,
            (RECONCILIATION, RECONCILIATION, case_id),
        )
        response = await client.post("/api/v1/automation/run", headers=admin)
        check(
            "cleared conditions resolve alerts",
            response.status_code == 200
            and response.json()["alerts_resolved"] >= 5,
        )

    print(
        json.dumps(
            {"status": "PASS", "tests": len(results), "results": results},
            indent=2,
        )
    )


asyncio.run(run())
