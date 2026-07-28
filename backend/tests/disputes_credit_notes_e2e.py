"""End-to-end dispute workflow tests against a disposable PostgreSQL database."""

import asyncio
import hashlib
import json
import os
from uuid import uuid4

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token


DSN = os.environ.get(
    "TEST_DATABASE_DSN",
    "postgresql://sentinel_test:sentinel_test_local_only@db:5432/"
    "price_sentinel_disputes_test",
)
VENUE_A = str(uuid4())
VENUE_B = str(uuid4())
RECONCILIATION_A = str(uuid4())
RECONCILIATION_B = str(uuid4())
SUPPLIER_ORDER_A = str(uuid4())
SUPPLIER_ORDER_B = str(uuid4())
ORDER_A = str(uuid4())
ORDER_B = str(uuid4())
results: list[str] = []


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


def invoice_fingerprint() -> str:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  coalesce(string_agg(
                    f.id::text || ':' || f.numero_documento || ':'
                    || f.tipo_documento::text || ':'
                    || f.totale_imponibile::text,
                    '|' order by f.id
                  ), ''),
                  coalesce(string_agg(
                    r.id::text || ':' || coalesce(r.descrizione_fornitore_raw, '')
                    || ':' || r.quantita::text || ':'
                    || r.prezzo_unitario_fatturato::text,
                    '|' order by r.id
                  ), '')
                from fatture f
                left join righe_fattura r on r.fattura_id = f.id
                """
            )
            return hashlib.sha256(
                "|".join(cursor.fetchone()).encode("utf-8")
            ).hexdigest()


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into location(id,nome_struttura,piva_riferimento,tipologia)
                values
                  (1,'Venue A','00000000001','ristorante'),
                  (2,'Venue B','00000000002','ristorante');

                insert into utenti(
                  id,email,password_hash,ruolo,location_id,attivo,
                  refresh_token_version
                ) values
                  (1,'admin@test.local','x','admin',null,true,1),
                  (2,'manager-a@test.local','x','manager',1,true,1),
                  (3,'manager-b@test.local','x','manager',2,true,1);

                insert into fornitori(
                  id,partita_iva,nome_azienda,attivo_whitelist,email_contatto
                ) values
                  (1,'10000000001','Supplier A',true,'supplier@example.test'),
                  (2,'10000000002','Supplier B',true,null);

                insert into xml_raw(
                  id,payload,hash_idempotenza,source,stato_ingestion,
                  data_ricezione
                ) values
                  (1,'<invoice immutable="1"/>',
                   'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                   'upload_manuale','parsato',now()),
                  (2,'<invoice immutable="2"/>',
                   'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                   'upload_manuale','parsato',now()),
                  (3,'<credit immutable="3"/>',
                   'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                   'upload_manuale','parsato',now()),
                  (4,'<credit immutable="4"/>',
                   'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
                   'upload_manuale','parsato',now());

                insert into fatture(
                  id,xml_raw_id,fornitore_id,location_id,numero_documento,
                  data_documento,data_ricezione_sdi,tipo_documento,
                  totale_imponibile,marker
                ) values
                  (1,1,1,1,'INV-A','2026-07-20','2026-07-20','TD01',50,'contestata'),
                  (2,2,1,2,'INV-B','2026-07-20','2026-07-20','TD01',20,'contestata'),
                  (3,3,1,1,'NC-A-2','2026-07-28','2026-07-28','TD04',15,'nessuno'),
                  (4,4,1,2,'NC-WRONG','2026-07-28','2026-07-28','TD04',15,'nessuno');

                insert into righe_fattura(
                  id,fattura_id,numero_linea,codice_fornitore_raw,
                  descrizione_fornitore_raw,sku_interno,
                  prezzo_unitario_fatturato,sconto_percentuale,
                  prezzo_netto_normalizzato,quantita,unita_misura_fattura,
                  is_omaggio,stato_matching
                ) values
                  (1,1,1,'SKU-A','Prodotto contestato A','SKU-A',15,0,15,2,'pz',false,'matched'),
                  (2,2,1,'SKU-B','Prodotto contestato B','SKU-B',10,0,10,2,'pz',false,'matched');

                insert into anomalie(
                  id,riga_fattura_id,delta_prezzo,delta_totale,
                  prezzo_listino_snapshot,prezzo_fatturato_snapshot,
                  stato_validazione
                ) values
                  (1,1,5,10,10,15,'contestata'),
                  (2,2,2,4,8,10,'contestata');
                """
            )
            cursor.execute(
                """
                insert into liquidstock_venue_mappings(
                  liquidstock_venue_id,location_id,venue_name_snapshot,
                  created_at,updated_at
                ) values
                  (%s,1,'Venue A',now(),now()),
                  (%s,2,'Venue B',now(),now());

                insert into purchase_order_reconciliations(
                  id,liquidstock_supplier_order_id,liquidstock_order_id,
                  supplier_id,venue_id,status,matching_confidence,
                  reconciliation_version,price_tolerance_absolute,
                  price_tolerance_percent,created_at,updated_at
                ) values
                  (%s,%s,%s,1,%s,'anomalies_found',1,1,.01,1,now(),now()),
                  (%s,%s,%s,1,%s,'anomalies_found',1,1,.01,1,now(),now());
                """,
                (
                    VENUE_A,
                    VENUE_B,
                    RECONCILIATION_A,
                    SUPPLIER_ORDER_A,
                    ORDER_A,
                    VENUE_A,
                    RECONCILIATION_B,
                    SUPPLIER_ORDER_B,
                    ORDER_B,
                    VENUE_B,
                ),
            )
            cursor.execute(
                """
                insert into purchase_order_reconciliation_anomalies(
                  id,reconciliation_id,fattura_id,riga_fattura_id,
                  liquidstock_supplier_order_id,supplier_id,venue_id,
                  anomaly_type,disputed_amount,evidence_key,evidence,
                  workflow_status,created_at,updated_at
                ) values
                  (101,%s,1,1,%s,1,%s,'price_overcharge',25,
                   'test-a','{"description":"Prodotto A"}',
                   'contestata',now(),now()),
                  (102,%s,2,2,%s,1,%s,'price_overcharge',5,
                   'test-b','{"description":"Prodotto B"}',
                   'contestata',now(),now());
                """,
                (
                    RECONCILIATION_A,
                    SUPPLIER_ORDER_A,
                    VENUE_A,
                    RECONCILIATION_B,
                    SUPPLIER_ORDER_B,
                    VENUE_B,
                ),
            )


async def run() -> None:
    seed()
    before_fingerprint = invoice_fingerprint()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager_a = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    manager_b = {"Authorization": f"Bearer {create_access_token(3, 'manager')}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        async def call(method, path, headers=manager_a, body=None, files=None):
            return await client.request(
                method, path, headers=headers, json=body, files=files
            )

        response = await call("GET", "/api/v1/disputes/candidates")
        check(
            "manager candidates are location scoped",
            response.status_code == 200
            and {item["location_id"] for item in response.json()} == {1},
        )

        response = await call(
            "POST",
            "/api/v1/disputes",
            headers=manager_b,
            body={
                "title": "Cross venue forbidden",
                "anomalies": [{"reconciliation_anomaly_id": 101}],
            },
        )
        check("manager cross venue create blocked", response.status_code == 403)

        response = await call(
            "POST",
            "/api/v1/disputes",
            body={
                "title": "Supplier A overcharge",
                "due_date": "2026-08-10",
                "anomalies": [{"reconciliation_anomaly_id": 101}],
            },
        )
        check("reconciliation dispute created", response.status_code == 201)
        case = response.json()
        case_id = case["id"]
        anomaly_id = case["anomalies"][0]["id"]
        check(
            "requested amount derives from explicit anomaly",
            case["requested_amount"] == "25.000000",
        )

        response = await call(
            "POST",
            "/api/v1/disputes",
            body={
                "title": "Duplicate blocked",
                "anomalies": [{"reconciliation_anomaly_id": 101}],
            },
        )
        check("duplicate anomaly blocked", response.status_code == 409)

        response = await call(
            "POST",
            "/api/v1/disputes",
            headers=admin,
            body={
                "title": "Mixed venue blocked",
                "anomalies": [
                    {"reconciliation_anomaly_id": 102},
                    {"legacy_anomaly_id": 1},
                ],
            },
        )
        check("mixed source or venue blocked", response.status_code == 409)

        response = await call(
            "GET", f"/api/v1/disputes/{case_id}", headers=manager_b
        )
        check("manager cross venue read blocked", response.status_code == 403)

        response = await call(
            "PATCH",
            f"/api/v1/disputes/{case_id}",
            body={"expected_version": 99, "title": "Stale update"},
        )
        check("optimistic lock blocks stale update", response.status_code == 409)

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/transition",
            body={
                "expected_version": case["version"],
                "target_status": "ready_to_send",
            },
        )
        check("draft becomes ready", response.status_code == 200)
        case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/communications",
            body={"channel": "email"},
        )
        check("recipient required for email", response.status_code == 422)

        custom_body = "Messaggio verificato manualmente — caso test"
        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/communications",
            body={
                "channel": "email",
                "recipient": "supplier@example.test",
                "subject": "Contestazione controllata",
                "body_override": custom_body,
            },
        )
        check(
            "editable communication snapshot prepared",
            response.status_code == 201
            and response.json()["body_snapshot"] == custom_body,
        )
        communication_id = response.json()["id"]

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/communications/"
            f"{communication_id}/events",
            body={"action": "opened"},
        )
        check(
            "opening is not delivery proof",
            response.status_code == 200
            and response.json()["status"] == "ready_to_send",
        )

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/communications/"
            f"{communication_id}/events",
            body={"action": "confirmed"},
        )
        check(
            "manual send confirmation starts dispute",
            response.status_code == 200 and response.json()["status"] == "sent",
        )
        case = response.json()
        check(
            "source reconciliation anomaly escalated after confirmation",
            scalar(
                "select workflow_status from "
                "purchase_order_reconciliation_anomalies where id=101"
            )
            == "in_reclamo",
        )

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/responses",
            body={
                "channel": "email",
                "response_text": "Riconosciamo l'addebito.",
                "received_at": "2026-07-28T12:00:00Z",
                "communication_id": communication_id,
            },
        )
        check(
            "supplier response recorded",
            response.status_code == 201
            and response.json()["status"] == "supplier_replied",
        )
        case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/recognition",
            body={
                "expected_version": case["version"],
                "allocations": [
                    {"case_anomaly_id": anomaly_id, "amount": "25.00"}
                ],
            },
        )
        check(
            "recognized amount recorded",
            response.status_code == 200
            and response.json()["status"] == "credit_note_expected",
        )
        case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/attachments",
            files={"file": ("evidence.txt", b"immutable evidence", "text/plain")},
        )
        check(
            "evidence attachment accepted",
            response.status_code == 201
            and response.json()["sha256"]
            == hashlib.sha256(b"immutable evidence").hexdigest(),
        )

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/attachments",
            files={"file": ("unsafe.exe", b"unsafe", "application/octet-stream")},
        )
        check("unsafe attachment blocked", response.status_code == 415)

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/credit-notes",
            body={
                "document_number": "NC-A-1",
                "issue_date": "2026-07-27",
                "total_amount": "10.00",
                "source": "manual",
                "allocations": [
                    {"case_anomaly_id": anomaly_id, "amount": "10.00"}
                ],
            },
        )
        check(
            "partial credit recovery recorded",
            response.status_code == 201
            and response.json()["status"] == "partially_recovered"
            and response.json()["recovered_amount"] == "10.000000",
        )
        case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/credit-notes",
            body={
                "document_number": "NC-A-1",
                "issue_date": "2026-07-27",
                "total_amount": "10.00",
                "source": "manual",
                "allocations": [
                    {"case_anomaly_id": anomaly_id, "amount": "10.00"}
                ],
            },
        )
        check("duplicate credit note blocked", response.status_code == 409)

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/credit-notes",
            body={
                "document_number": "NC-WRONG",
                "issue_date": "2026-07-28",
                "total_amount": "15.00",
                "source": "imported",
                "fattura_id": 4,
                "allocations": [
                    {"case_anomaly_id": anomaly_id, "amount": "15.00"}
                ],
            },
        )
        check("cross venue TD04 blocked", response.status_code == 409)

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/credit-notes",
            body={
                "document_number": "NC-A-2",
                "issue_date": "2026-07-28",
                "total_amount": "15.00",
                "source": "imported",
                "fattura_id": 3,
                "allocations": [
                    {"case_anomaly_id": anomaly_id, "amount": "15.00"}
                ],
            },
        )
        check(
            "TD04 completes recovery without mutating invoice",
            response.status_code == 201
            and response.json()["status"] == "recovered"
            and response.json()["unrecovered_amount"] == "0.000000",
        )
        case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{case_id}/transition",
            body={
                "expected_version": case["version"],
                "target_status": "closed",
                "reason": "Recupero completato e verificato",
            },
        )
        check(
            "recovered case can be closed with reason",
            response.status_code == 200 and response.json()["status"] == "closed",
        )
        closed_case = response.json()

        response = await call(
            "PATCH",
            f"/api/v1/disputes/{case_id}",
            body={
                "expected_version": closed_case["version"],
                "title": "Forbidden mutation",
            },
        )
        check("terminal case immutable", response.status_code == 409)

        response = await call(
            "POST",
            "/api/v1/disputes",
            body={
                "title": "Legacy price anomaly",
                "anomalies": [{"legacy_anomaly_id": 1, "claimed_amount": "10"}],
            },
        )
        check("legacy anomaly dispute created", response.status_code == 201)
        legacy_case = response.json()

        response = await call(
            "POST",
            f"/api/v1/disputes/{legacy_case['id']}/transition",
            body={
                "expected_version": legacy_case["version"],
                "target_status": "ready_to_send",
            },
        )
        legacy_case = response.json()
        response = await call(
            "POST",
            f"/api/v1/disputes/{legacy_case['id']}/communications",
            body={"channel": "copy"},
        )
        legacy_communication = response.json()
        response = await call(
            "POST",
            f"/api/v1/disputes/{legacy_case['id']}/communications/"
            f"{legacy_communication['id']}/events",
            body={"action": "confirmed"},
        )
        check(
            "legacy anomaly escalates only after confirmation",
            response.status_code == 200
            and scalar("select stato_validazione::text from anomalie where id=1")
            == "in_reclamo",
        )

        response = await call("GET", "/api/v1/disputes/dashboard")
        dashboard = response.json()
        check(
            "economic dashboard reconciles recovery",
            response.status_code == 200
            and dashboard["total_recovered"] == "25.000000"
            and dashboard["total_outstanding"] == "10.000000",
        )

        response = await call("GET", f"/api/v1/disputes/{case_id}/pdf")
        check(
            "supplier dossier PDF generated",
            response.status_code == 200
            and response.headers["content-type"] == "application/pdf"
            and response.content.startswith(b"%PDF"),
        )

    check(
        "source invoices and invoice lines remain immutable",
        invoice_fingerprint() == before_fingerprint,
    )
    check(
        "audit trail covers lifecycle",
        scalar(
            "select count(*) from dispute_audit_events "
            "where dispute_case_id=%s",
            (case_id,),
        )
        >= 8,
    )
    print(
        json.dumps(
            {"status": "PASS", "tests": len(results), "results": results},
            indent=2,
        ),
        flush=True,
    )


asyncio.run(run())
