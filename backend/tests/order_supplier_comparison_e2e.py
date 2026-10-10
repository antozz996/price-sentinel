"""Phase 12 price comparisons across competing suppliers (synthetic CI only).

Read/write assertions require a fresh disposable PostgreSQL on GitHub-hosted CI.
No integration, WhatsApp messages or actual supplier orders are delivered.
"""
from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token

DSN = os.environ["TEST_DATABASE_DSN"]


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def scalar(query: str):
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchone()[0]


def seed() -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                insert into location(id,nome_struttura,piva_riferimento,tipologia,tenant_id)
                values
                    (1,'Synthetic buyer A','00000000001','ristorante',1),
                    (2,'Synthetic buyer B','00000000002','ristorante',2);
                insert into utenti(id,email,password_hash,ruolo,location_id,tenant_id,attivo,refresh_token_version)
                values
                    (1,'synthetic-a@example.test','x','admin',null,1,true,1),
                    (2,'synthetic-b@example.test','x','admin',null,2,true,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values
                    (1,'10000000001','Supplier A',true),
                    (2,'10000000002','Supplier B',true),
                    (3,'10000000003','Supplier disabled',false);
                insert into xml_raw(
                    id,payload,hash_idempotenza,source,stato_ingestion,data_ricezione)
                select i, '<synthetic/>', repeat(chr(96+i),64), 'upload_manuale','parsato',now()
                from generate_series(1,5) i;
                insert into fatture(
                    id,xml_raw_id,fornitore_id,location_id,tenant_id,
                    numero_documento,data_documento,data_ricezione_sdi,
                    tipo_documento,totale_imponibile)
                values
                    (1,1,1,1,1,'A1','2026-10-01','2026-10-01','TD01',21),
                    (2,2,2,1,1,'B1','2026-10-01','2026-10-01','TD01',27),
                    (3,3,3,1,1,'DISABLED','2026-10-01','2026-10-01','TD01',3),
                    (4,4,2,2,2,'B-T2','2026-10-01','2026-10-01','TD01',3),
                    (5,5,1,1,1,'PROMO','2026-10-01','2026-10-01','TD01',0);
                insert into righe_fattura(
                    id,fattura_id,numero_linea,codice_fornitore_raw,
                    descrizione_fornitore_raw,sku_interno,
                    prezzo_unitario_fatturato,sconto_percentuale,
                    prezzo_netto_normalizzato,quantita,unita_misura_fattura,
                    is_omaggio,stato_matching)
                values
                    (1,1,1,'SKU','Synthetic spot','SPOT-CI',7,0,7,3,'pz',false,'matched'),
                    (2,2,1,'SKU','Synthetic spot','SPOT-CI',9,0,9,3,'pz',false,'matched'),
                    (3,3,1,'SKU','Synthetic spot','SPOT-CI',1,0,1,3,'pz',false,'matched'),
                    (4,4,1,'SKU','Synthetic spot','SPOT-CI',1,0,1,3,'pz',false,'matched'),
                    (5,5,1,'SKU','Synthetic spot','SPOT-CI',0,0,0,3,'pz',true,'matched');
            """)


async def run() -> None:
    seed()
    admin_a = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    admin_b = {"Authorization": f"Bearer {create_access_token(2, 'admin')}"}
    basket = [{"sku_interno": "SPOT-CI", "quantita": 3, "prezzo_inserito": 10.0}]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        r = await client.post("/api/v1/ordini/ottimizza", headers=admin_a, json=basket)
        check("tenant A spot optimizer responds", r.status_code == 200)
        item = r.json()["righe_ottimizzate"][0]
        check("best active local supplier selected at net VAT-excluded price",
              item["tipo_regola"] == "spot_ottimale"
              and item["fornitore_id"] == 1
              and Decimal(str(item["prezzo_ottimale"])) == 7)
        check("no disabled, other-tenant or gift price contaminates comparison",
              {p["fornitore_id"] for p in item["confronto_prezzi"]} == {1,2}
              and {Decimal(str(p["prezzo"])) for p in item["confronto_prezzi"]} == {7,9})
        check("buyer warned about higher entered price",
              item["is_anomalia"] is True and r.json()["sintesi"]["numero_anomalie"] == 1)
        check("cross-supplier potential difference uses 9 vs 7 times 3",
              Decimal(str(r.json()["sintesi"]["risparmio_preventivo_stimato"])) == 6)

        r = await client.post("/api/v1/ordini/ottimizza", headers=admin_b, json=basket)
        check("tenant B sees only its own invoice history",
              r.status_code == 200
              and r.json()["righe_ottimizzate"][0]["fornitore_id"] == 2
              and Decimal(str(r.json()["righe_ottimizzate"][0]["prezzo_ottimale"])) == 1
              and len(r.json()["righe_ottimizzate"][0]["confronto_prezzi"]) == 1)

        r = await client.post(
            "/api/v1/ordini/crea", headers=admin_a,
            json={"location_id": 1, "items": [{"sku_interno": "SPOT-CI", "quantita": 3, "prezzo_inserito": 7}]},
        )
        check("spot-based purchase order saved for authorized tenant",
              r.status_code == 200 and len(r.json()) == 1)
        check("saved order selects best seller and keeps tenant ownership",
              scalar("select count(*) from ordini where fornitore_id=1 and tenant_id=1 and location_id=1") == 1)

    print(json.dumps({"status": "PASS", "scenario": "synthetic cross-supplier spot optimization"}), flush=True)


if __name__ == "__main__":
    asyncio.run(run())
