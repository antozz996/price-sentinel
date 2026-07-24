"""End-to-end tests for the signed LiquidStock inbound API.

Run only against the disposable Sprint 4 database.
"""

import hashlib
import hmac
import json
import os
import time
from uuid import uuid4

import httpx
import psycopg2


BASE_URL = os.environ.get("INTEGRATION_TEST_BASE_URL", "http://127.0.0.1:18001")
DATABASE_DSN = os.environ["INTEGRATION_TEST_DATABASE_DSN"]
SECRET = os.environ["LIQUIDSTOCK_INTEGRATION_SECRET"]
results: list[str] = []


def check(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)
    results.append(name)


def signed_headers(
    raw: bytes,
    event_id: str,
    *,
    timestamp: int | None = None,
    secret: str = SECRET,
    source: str = "liquidstock",
):
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Integration-Source": source,
        "X-Event-Id": event_id,
        "X-Event-Timestamp": str(timestamp),
        "X-Event-Signature": signature,
    }


def post_event(
    payload: dict,
    event_id: str | None = None,
    *,
    signed_raw: bytes | None = None,
    timestamp: int | None = None,
    secret: str = SECRET,
    source: str = "liquidstock",
):
    event_id = event_id or str(uuid4())
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = signed_headers(
        signed_raw if signed_raw is not None else raw,
        event_id,
        timestamp=timestamp,
        secret=secret,
        source=source,
    )
    return event_id, httpx.post(
        f"{BASE_URL}/api/v1/integrations/liquidstock/events",
        content=raw,
        headers=headers,
        timeout=10,
    )


def catalog(kind: str, body: dict):
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    return httpx.post(
        f"{BASE_URL}/api/v1/integrations/liquidstock/catalog/{kind}/search",
        content=raw,
        headers=signed_headers(raw, str(uuid4())),
        timeout=10,
    )


def payload(
    event_type: str,
    order_id: str,
    supplier_order_id: str,
    supplier_id: str,
    rows: list[dict],
    *,
    version: str = "1.0",
    receipt: dict | None = None,
    venue_id: str | None = None,
):
    value = {
        "integration_version": version,
        "event_type": event_type,
        "liquidstock_order_id": order_id,
        "liquidstock_supplier_order_id": supplier_order_id,
        "venue_id": venue_id or str(uuid4()),
        "venue_name_snapshot": "Venue test Sprint 4",
        "supplier_id": supplier_id,
        "price_sentinel_supplier_id": "1",
        "supplier_name_snapshot": "Supplier canonical test",
        "sent_at": "2026-07-24T10:00:00Z",
        "requested_delivery_date": "2026-07-30",
        "order_version": 1,
        "rows": rows,
    }
    if event_type == "supplier_order_received":
        value["received_at"] = "2026-07-24T12:00:00Z"
        value["receipt"] = receipt
    if event_type == "supplier_order_cancelled":
        value["cancelled_at"] = "2026-07-24T13:00:00Z"
    return value


row_one_id = str(uuid4())
row_two_id = str(uuid4())
rows = [
    {
        "supplier_order_item_id": row_one_id,
        "product_id": str(uuid4()),
        "price_sentinel_product_id": "1",
        "product_name_snapshot": "Canonical mapped row",
        "quantity": 5,
        "unit": "cartoni",
        "package_note": "6 x 1 L",
        "supplier_note": "Mattina",
    },
    {
        "supplier_order_item_id": row_two_id,
        "product_id": None,
        "price_sentinel_product_id": None,
        "product_name_snapshot": "Free unmapped row",
        "quantity": 2,
        "unit": "kg",
        "package_note": None,
        "supplier_note": None,
    },
]


with psycopg2.connect(DATABASE_DSN) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
            values (1,'00000000001','Supplier canonical test',true)
            on conflict (id) do nothing
            """
        )
        cursor.execute(
            """
            insert into products(
              id,canonical_name,comparison_unit,is_active,is_commodity,
              unit_count,created_at,updated_at
            ) values (1,'Product canonical test','unit',true,false,1,now(),now())
            on conflict (id) do nothing
            """
        )
        cursor.execute(
            """
            select
              (select count(*) from fatture),
              (select count(*) from righe_fattura),
              (select count(*) from listino_master),
              (select count(*) from anomalie)
            """
        )
        untouched_before = cursor.fetchone()

base_order = str(uuid4())
base_supplier_order = str(uuid4())
base_supplier = str(uuid4())
base_venue = str(uuid4())
confirmed = payload(
    "supplier_order_confirmed",
    base_order,
    base_supplier_order,
    base_supplier,
    rows,
    venue_id=base_venue,
)
raw_confirmed = json.dumps(confirmed, separators=(",", ":"), sort_keys=True).encode()

response = httpx.post(
    f"{BASE_URL}/api/v1/integrations/liquidstock/events",
    content=raw_confirmed,
    timeout=10,
)
check("missing signature rejected", response.status_code == 401)

_, response = post_event(confirmed, secret="wrong-test-secret")
check("invalid signature rejected", response.status_code == 401)

_, response = post_event(confirmed, timestamp=int(time.time()) - 301)
check("expired timestamp rejected", response.status_code == 401)

_, response = post_event(confirmed, timestamp=int(time.time()) + 301)
check("future timestamp rejected", response.status_code == 401)

_, response = post_event(confirmed, source="other-system")
check("invalid source rejected", response.status_code == 401)

modified = dict(confirmed)
modified["venue_name_snapshot"] = "Modified after signing"
_, response = post_event(modified, signed_raw=raw_confirmed)
check("body modified after signature rejected", response.status_code == 401)

confirmed_event, response = post_event(confirmed)
check("confirmed event accepted", response.status_code == 200)
check("first delivery is not duplicate", response.json()["duplicate"] is False)

_, response = post_event(confirmed, event_id=confirmed_event)
check("same event accepted idempotently", response.status_code == 200)
check("duplicate response true", response.json()["duplicate"] is True)

conflicting = dict(confirmed)
conflicting["venue_name_snapshot"] = "Conflicting payload"
_, response = post_event(conflicting, event_id=confirmed_event)
check("same event id with different payload rejected", response.status_code == 409)

partial_receipt_id = str(uuid4())
partial = payload(
    "supplier_order_received",
    base_order,
    base_supplier_order,
    base_supplier,
    rows,
    venue_id=base_venue,
    receipt={
        "id": partial_receipt_id,
        "status": "partial",
        "items": [
            {
                "supplier_order_item_id": row_one_id,
                "ordered_quantity": 5,
                "received_quantity": 2,
                "missing_quantity": 3,
                "line_status": "partial",
                "note": None,
            },
            {
                "supplier_order_item_id": row_two_id,
                "ordered_quantity": 2,
                "received_quantity": 0,
                "missing_quantity": 2,
                "line_status": "not_delivered",
                "note": None,
            },
        ],
    },
)
_, response = post_event(partial)
check("partial receipt accepted", response.status_code == 200)

complete = payload(
    "supplier_order_received",
    base_order,
    base_supplier_order,
    base_supplier,
    rows,
    venue_id=base_venue,
    receipt={
        "id": str(uuid4()),
        "status": "complete",
        "items": [
            {
                "supplier_order_item_id": row_one_id,
                "ordered_quantity": 5,
                "received_quantity": 6,
                "missing_quantity": 0,
                "line_status": "over_received",
                "note": "One extra",
            },
            {
                "supplier_order_item_id": row_two_id,
                "ordered_quantity": 2,
                "received_quantity": 2,
                "missing_quantity": 0,
                "line_status": "received",
                "note": None,
            },
        ],
    },
)
_, response = post_event(complete)
check("complete cumulative receipt accepted", response.status_code == 200)

second_supplier_order = str(uuid4())
second_rows = [{**rows[0], "supplier_order_item_id": str(uuid4())}]
second_confirmed = payload(
    "supplier_order_confirmed",
    base_order,
    second_supplier_order,
    str(uuid4()),
    second_rows,
)
_, response = post_event(second_confirmed)
check("second supplier under same general order accepted", response.status_code == 200)
second_cancelled = payload(
    "supplier_order_cancelled",
    base_order,
    second_supplier_order,
    second_confirmed["supplier_id"],
    second_rows,
)
second_cancelled["venue_id"] = second_confirmed["venue_id"]
_, response = post_event(second_cancelled)
check("cancelled event accepted", response.status_code == 200)

out_of_order_order = str(uuid4())
out_of_order_supplier_order = str(uuid4())
out_of_order_supplier = str(uuid4())
out_of_order_rows = [{**rows[0], "supplier_order_item_id": str(uuid4())}]
out_of_order_received = payload(
    "supplier_order_received",
    out_of_order_order,
    out_of_order_supplier_order,
    out_of_order_supplier,
    out_of_order_rows,
    receipt={
        "id": str(uuid4()),
        "status": "complete",
        "items": [{
            "supplier_order_item_id": out_of_order_rows[0]["supplier_order_item_id"],
            "ordered_quantity": 5,
            "received_quantity": 5,
            "missing_quantity": 0,
            "line_status": "received",
            "note": None,
        }],
    },
)
out_of_order_event, response = post_event(out_of_order_received)
check("out-of-order receipt rejected", response.status_code == 409)
out_of_order_confirmed = payload(
    "supplier_order_confirmed",
    out_of_order_order,
    out_of_order_supplier_order,
    out_of_order_supplier,
    out_of_order_rows,
)
out_of_order_confirmed["venue_id"] = out_of_order_received["venue_id"]
_, response = post_event(out_of_order_confirmed)
check("missing prerequisite can arrive later", response.status_code == 200)
_, response = post_event(out_of_order_received, event_id=out_of_order_event)
check("failed event can be replayed idempotently", response.status_code == 200)
check("replayed event reports duplicate", response.json()["duplicate"] is True)

unsupported = payload(
    "supplier_order_confirmed",
    str(uuid4()),
    str(uuid4()),
    str(uuid4()),
    [{**rows[0], "supplier_order_item_id": str(uuid4())}],
    version="2.0",
)
_, response = post_event(unsupported)
check("unsupported integration version rejected", response.status_code == 422)

invalid_mapping = payload(
    "supplier_order_confirmed",
    str(uuid4()),
    str(uuid4()),
    str(uuid4()),
    [{**rows[0], "supplier_order_item_id": str(uuid4())}],
)
invalid_mapping["price_sentinel_supplier_id"] = "999999"
_, response = post_event(invalid_mapping)
check("unknown supplier mapping rejected", response.status_code == 422)

response = catalog("suppliers", {"query": "canonical", "limit": 20})
check("supplier catalog search works", response.status_code == 200 and len(response.json()) == 1)
response = catalog("products", {"id": 1, "limit": 1})
check("product catalog exact lookup works", response.status_code == 200 and response.json()[0]["id"] == 1)
response = catalog("products", {"id": 999999, "limit": 1})
check("unknown product catalog id returns empty", response.status_code == 200 and response.json() == [])

with psycopg2.connect(DATABASE_DSN) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from liquidstock_integration_events where external_event_id=%s",
            (confirmed_event,),
        )
        check("one event row for duplicate delivery", cursor.fetchone()[0] == 1)
        cursor.execute(
            """
            select count(*) from liquidstock_supplier_orders
            where liquidstock_supplier_order_id=%s
            """,
            (base_supplier_order,),
        )
        check("one supplier order projection", cursor.fetchone()[0] == 1)
        cursor.execute(
            """
            select status from liquidstock_supplier_orders
            where liquidstock_supplier_order_id=%s
            """,
            (base_supplier_order,),
        )
        check("cumulative flow ends received", cursor.fetchone()[0] == "received")
        cursor.execute(
            """
            select received_quantity
            from liquidstock_supplier_order_items item
            join liquidstock_supplier_orders supplier_order
              on supplier_order.id=item.supplier_order_id
            where supplier_order.liquidstock_supplier_order_id=%s
              and item.liquidstock_supplier_order_item_id=%s
            """,
            (base_supplier_order, row_one_id),
        )
        check("latest cumulative quantity persisted", float(cursor.fetchone()[0]) == 6)
        cursor.execute(
            """
            select processing_status,processing_error
            from liquidstock_integration_events
            where external_event_id=%s
            """,
            (out_of_order_event,),
        )
        check("replayed out-of-order event becomes processed", cursor.fetchone() == ("processed", None))
        cursor.execute(
            """
            select
              (select count(*) from fatture),
              (select count(*) from righe_fattura),
              (select count(*) from listino_master),
              (select count(*) from anomalie)
            """
        )
        check("invoice price-list anomaly tables unchanged", cursor.fetchone() == untouched_before)

print(json.dumps({"status": "PASS", "tests": len(results), "results": results}, indent=2))
