"""End-to-end tests for explicit, audited supplier identity equivalences.

Run only against a fresh disposable database migrated to Alembic head.
"""

import asyncio
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
    "price_sentinel_supplier_equivalence_test",
)
VENUE_A = str(uuid4())
VENUE_B = str(uuid4())
ORDER_A = str(uuid4())
ORDER_B = str(uuid4())
SUPPLIER_ORDER_A = str(uuid4())
SUPPLIER_ORDER_B = str(uuid4())
ITEM_A = str(uuid4())
EVENT_A = str(uuid4())
results: list[str] = []


def check(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)
    results.append(name)


def scalar(sql: str, args: tuple = ()):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
            row = cursor.fetchone()
            return row[0] if row else None


def fingerprint() -> tuple[int, int, int, int, int, int]:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select
                  (select count(*) from fornitori),
                  (select count(*) from fatture),
                  (select count(*) from righe_fattura),
                  (select count(*) from listino_master),
                  (select count(*) from supplier_product_aliases),
                  (select count(*) from anomalie)
                """
            )
            return cursor.fetchone()


def seed():
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into location(
                  id,nome_struttura,piva_riferimento,tipologia
                ) values
                  (1,'Test Venue A','00000000001','ristorante'),
                  (2,'Test Venue B','00000000002','ristorante');

                insert into utenti(
                  id,email,password_hash,ruolo,location_id,attivo,
                  refresh_token_version
                ) values
                  (1,'admin@test.local','x','admin',null,true,1),
                  (2,'manager@test.local','x','manager',1,true,1);

                insert into fornitori(
                  id,partita_iva,nome_azienda,attivo_whitelist
                ) values
                  (7,'10000000007','Navas Distribuzione srl',true),
                  (11,'10000000011','Navas Srl',true),
                  (12,'10000000012','Fornitore terzo',true),
                  (13,'10000000013','Fornitore quarto',true);

                insert into products(
                  id,sku_interno,canonical_name,normalized_name,
                  comparison_unit,is_commodity,is_active,unit_count,
                  created_at,updated_at
                ) values (
                  59,'ACQ-ELECTA-100CL','Acqua Electa 1L PET',
                  'acqua electa 1l pet','pz',false,true,1,now(),now()
                );

                insert into supplier_product_aliases(
                  id,supplier_id,product_id,supplier_code,raw_description,
                  normalized_description,ean,status,confidence_score,source,
                  first_seen_at,last_seen_at,created_at,updated_at
                ) values (
                  1,11,59,'NAVAS-ELECTA-1L','Acqua Electa 1L PET',
                  'acqua electa 1l pet',null,'approved',1,'test',
                  now(),now(),now(),now()
                );

                insert into xml_raw(
                  id,payload,hash_idempotenza,source,stato_ingestion,
                  data_ricezione
                ) values
                  (101,'<x/>',repeat('a',64),'upload_manuale','parsato',now()),
                  (102,'<x/>',repeat('b',64),'upload_manuale','parsato',now()),
                  (103,'<x/>',repeat('c',64),'upload_manuale','parsato',now()),
                  (104,'<x/>',repeat('d',64),'upload_manuale','parsato',now());

                insert into fatture(
                  id,xml_raw_id,fornitore_id,location_id,numero_documento,
                  data_documento,data_ricezione_sdi,tipo_documento,
                  totale_imponibile,marker
                ) values
                  (101,101,7,1,'INV-NAVAS-1','2026-07-25','2026-07-25',
                   'TD01',10,'nessuno'),
                  (102,102,12,1,'INV-THIRD','2026-07-25','2026-07-25',
                   'TD01',10,'nessuno'),
                  (103,103,7,2,'INV-WRONG-VENUE','2026-07-25','2026-07-25',
                   'TD01',10,'nessuno'),
                  (104,104,7,1,'INV-NAVAS-2','2026-07-26','2026-07-26',
                   'TD01',10,'nessuno');

                insert into righe_fattura(
                  id,fattura_id,numero_linea,codice_fornitore_raw,
                  descrizione_fornitore_raw,sku_interno,
                  prezzo_unitario_fatturato,sconto_percentuale,
                  prezzo_netto_normalizzato,quantita,unita_misura_fattura,
                  is_omaggio,stato_matching
                ) values
                  (101,101,1,'NAVAS-ELECTA-1L','Acqua Electa 1L PET',null,
                   10,0,10,1,'pz',false,'matched'),
                  (102,102,1,'THIRD','Prodotto terzo',null,
                   10,0,10,1,'pz',false,'no_match'),
                  (103,103,1,'NAVAS-ELECTA-1L','Acqua Electa 1L PET',null,
                   10,0,10,1,'pz',false,'matched'),
                  (104,104,1,'NAVAS-ELECTA-1L','Acqua Electa 1L PET',null,
                   10,0,10,1,'pz',false,'matched');
                """
            )
            cursor.execute(
                """
                insert into liquidstock_supplier_orders(
                  id,liquidstock_order_id,liquidstock_supplier_order_id,
                  liquidstock_venue_id,venue_name_snapshot,
                  liquidstock_supplier_id,supplier_id,supplier_name_snapshot,
                  order_version,status,sent_at,requested_delivery_date,
                  received_at,last_event_id,created_at,updated_at
                ) values
                  (1,%s,%s,%s,'Test Venue A',%s,11,'Navas Srl',1,
                   'received',now(),'2026-07-25',now(),%s,now(),now()),
                  (2,%s,%s,%s,'Test Venue A',%s,11,'Navas Srl',1,
                   'received',now(),'2026-07-25',now(),%s,now(),now())
                """,
                (
                    ORDER_A,
                    SUPPLIER_ORDER_A,
                    VENUE_A,
                    str(uuid4()),
                    EVENT_A,
                    ORDER_B,
                    SUPPLIER_ORDER_B,
                    VENUE_A,
                    str(uuid4()),
                    str(uuid4()),
                ),
            )
            cursor.execute(
                """
                insert into liquidstock_supplier_order_items(
                  id,supplier_order_id,liquidstock_supplier_order_item_id,
                  liquidstock_product_id,product_id,product_name_snapshot,
                  quantity,unit,package_note,ordered_quantity,
                  received_quantity,created_at,updated_at
                ) values (
                  1,1,%s,%s,59,'Acqua Electa 1L PET',
                  1,'pz','1 x 1 L',1,1,now(),now()
                )
                """,
                (ITEM_A, str(uuid4())),
            )


async def run():
    seed()
    untouched_before = fingerprint()
    alias_before = scalar("select count(*) from supplier_product_aliases")
    admin_headers = {
        "Authorization": f"Bearer {create_access_token(1, 'admin')}"
    }
    manager_headers = {
        "Authorization": f"Bearer {create_access_token(2, 'manager')}"
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        async def call(method, path, body=None, headers=admin_headers):
            return await client.request(
                method, path, headers=headers, json=body
            )

        response = await call(
            "POST",
            "/api/v1/reconciliations/venue-mappings",
            {
                "liquidstock_venue_id": VENUE_A,
                "location_id": 1,
            },
        )
        check("venue mapping created", response.status_code == 200)

        candidate_path = (
            "/api/v1/reconciliations/orders/"
            f"{SUPPLIER_ORDER_A}/invoice-candidates"
        )
        response = await call("GET", candidate_path)
        check(
            "without equivalence cross-supplier candidates hidden",
            response.status_code == 200 and response.json() == [],
        )
        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_A}/invoice",
            {"fattura_id": 101},
        )
        check(
            "without equivalence cross-supplier association blocked",
            response.status_code == 409,
        )

        create_payload = {
            "canonical_supplier_id": 7,
            "equivalent_supplier_id": 11,
            "reason": "Stessa identità commerciale verificata manualmente",
            "confirm": True,
        }
        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            create_payload,
            manager_headers,
        )
        check("manager cannot manage equivalences", response.status_code == 403)
        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            {**create_payload, "confirm": False},
        )
        check("explicit confirmation required", response.status_code == 422)
        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            {
                **create_payload,
                "canonical_supplier_id": 7,
                "equivalent_supplier_id": 7,
            },
        )
        check("self-equivalence blocked", response.status_code == 422)

        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            create_payload,
        )
        check(
            "explicit equivalence created",
            response.status_code == 200
            and response.json()["canonical_supplier_id"] == 7
            and response.json()["equivalent_supplier_id"] == 11
            and response.json()["is_active"] is True,
        )
        equivalence_id = response.json()["id"]
        check(
            "creation audit present",
            scalar(
                "select count(*) from supplier_identity_equivalence_audit "
                "where equivalence_id=%s and action='created'",
                (equivalence_id,),
            )
            == 1,
        )

        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            create_payload,
        )
        check("direct duplicate blocked", response.status_code == 409)
        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            {
                **create_payload,
                "canonical_supplier_id": 11,
                "equivalent_supplier_id": 7,
            },
        )
        check("inverse duplicate blocked", response.status_code == 409)
        response = await call(
            "POST",
            "/api/v1/reconciliations/supplier-equivalences",
            {
                **create_payload,
                "canonical_supplier_id": 11,
                "equivalent_supplier_id": 12,
            },
        )
        check(
            "cycle or transitive overlap blocked",
            response.status_code == 409,
        )

        response = await call("GET", candidate_path)
        candidates = response.json()
        check(
            "active equivalence exposes only equivalent supplier invoices",
            response.status_code == 200
            and {row["id"] for row in candidates} == {101, 104}
            and all(row["allowed_via_equivalence"] for row in candidates)
            and all(
                row["supplier_equivalence_id"] == equivalence_id
                for row in candidates
            ),
        )
        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_A}/invoice",
            {"fattura_id": 102},
        )
        check("third supplier remains blocked", response.status_code == 409)
        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_A}/invoice",
            {"fattura_id": 103},
        )
        check("cross-venue remains blocked", response.status_code == 409)

        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_A}/invoice",
            {"fattura_id": 101},
        )
        detail = response.json()
        check(
            "association preserves both supplier identities and audit snapshot",
            response.status_code == 200
            and detail["supplier_id"] == 11
            and detail["invoice_supplier_id"] == 7
            and detail["supplier_equivalence_id"] == equivalence_id
            and detail["supplier_equivalence_approved_by"] == 1
            and detail["supplier_equivalence_approved_at"]
            and detail["supplier_equivalence_used_at"]
            and detail["supplier_equivalence_reason_snapshot"]
            == create_payload["reason"],
        )
        reconciliation_id = detail["id"]

        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_B}/invoice",
            {"fattura_id": 101},
        )
        check("double invoice association blocked", response.status_code == 409)

        response = await call(
            "POST",
            f"/api/v1/reconciliations/{reconciliation_id}/match",
        )
        items = response.json()["items"]
        check(
            "equivalent supplier approved alias used",
            response.status_code == 200
            and len(items) == 1
            and items[0]["product_id"] == 59
            and items[0]["match_method"] == "supplier_product_alias"
            and items[0]["match_alias_supplier_id"] == 11
            and items[0]["match_alias_supplier_name"] == "Navas Srl",
        )
        check(
            "matching creates no aliases",
            scalar("select count(*) from supplier_product_aliases")
            == alias_before,
        )

        response = await call(
            "PATCH",
            f"/api/v1/reconciliations/supplier-equivalences/{equivalence_id}",
            {
                "is_active": False,
                "reason": "Disattivazione durante collaudo controllato",
                "confirm": True,
            },
        )
        check(
            "equivalence in open reconciliation cannot be deactivated",
            response.status_code == 409,
        )

        response = await call(
            "DELETE",
            f"/api/v1/reconciliations/{reconciliation_id}/invoice",
        )
        check(
            "invoice can be explicitly detached",
            response.status_code == 200
            and response.json()["supplier_id"] == 11
            and response.json()["invoice_supplier_id"] is None,
        )
        response = await call(
            "PATCH",
            f"/api/v1/reconciliations/supplier-equivalences/{equivalence_id}",
            {
                "is_active": False,
                "reason": "Disattivazione dopo scollegamento controllato",
                "confirm": True,
            },
        )
        check(
            "equivalence deactivated without deletion",
            response.status_code == 200
            and response.json()["is_active"] is False
            and scalar(
                "select count(*) from supplier_identity_equivalences "
                "where id=%s",
                (equivalence_id,),
            )
            == 1,
        )
        response = await call("GET", candidate_path)
        check(
            "deactivated equivalence hides candidates again",
            response.status_code == 200 and response.json() == [],
        )
        response = await call(
            "POST",
            f"/api/v1/reconciliations/orders/{SUPPLIER_ORDER_A}/invoice",
            {"fattura_id": 101},
        )
        check(
            "deactivated equivalence blocks association again",
            response.status_code == 409,
        )
        check(
            "deactivation audit present",
            scalar(
                "select count(*) from supplier_identity_equivalence_audit "
                "where equivalence_id=%s and action='deactivated'",
                (equivalence_id,),
            )
            == 1,
        )

        response = await call(
            "PATCH",
            f"/api/v1/reconciliations/supplier-equivalences/{equivalence_id}",
            {
                "is_active": True,
                "reason": "Riattivazione esplicita dopo verifica manuale",
                "confirm": True,
            },
        )
        check(
            "equivalence can be explicitly reactivated",
            response.status_code == 200
            and response.json()["is_active"] is True,
        )
        response = await call(
            "GET",
            "/api/v1/reconciliations/supplier-equivalences/audit"
            f"?equivalence_id={equivalence_id}",
        )
        check(
            "complete audit API visible to admin",
            response.status_code == 200
            and [row["action"] for row in response.json()]
            == ["activated", "deactivated", "created"],
        )
        response = await call(
            "GET",
            "/api/v1/reconciliations/supplier-equivalences",
            headers=manager_headers,
        )
        check("manager cannot read equivalence admin API", response.status_code == 403)

    check(
        "suppliers invoices lines price lists and anomalies unchanged",
        fingerprint() == untouched_before,
    )
    print(
        json.dumps(
            {"status": "PASS", "tests": len(results), "results": results},
            indent=2,
        ),
        flush=True,
    )


asyncio.run(run())
