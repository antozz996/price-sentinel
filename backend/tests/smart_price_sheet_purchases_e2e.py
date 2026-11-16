"""Listino Smart ordinato per acquisti/spesa su PostgreSQL usa e getta.

Verifica acquisti, spesa e ultimo acquisto per voce nella matrice (note di credito,
omaggi, righe e SKU esclusi, tenant, sede) e che l'ordinamento avvenga prima di
limit/offset. Solo tramite run_ci_disposable_e2e.py; dati sintetici.
"""
from __future__ import annotations

import asyncio
import os

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
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                insert into location(id,nome_struttura,piva_riferimento,tipologia,tenant_id)
                values (1,'Sede sintetica A','00000000001','ristorante',1),
                       (2,'Sede sintetica B','00000000002','ristorante',1),
                       (3,'Altro tenant','00000000003','ristorante',2);
                insert into utenti(id,email,password_hash,ruolo,location_id,tenant_id,attivo,refresh_token_version)
                values (1,'admin@example.test','x','admin',null,1,true,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Fornitore sintetico',true);
                insert into products(
                    id,sku_interno,canonical_name,normalized_name,category,comparison_unit,
                    is_commodity,is_active,unit_count,created_at,updated_at)
                values
                    (1,'MAT-A','Alfa piatti','alfa piatti','Materiali','Pz',false,true,1,now(),now()),
                    (2,'MAT-B','Beta bicchieri','beta bicchieri','Materiali','Pz',false,true,1,now(),now()),
                    (3,'MAT-C','Gamma tovaglioli','gamma tovaglioli','Materiali','Pz',false,true,1,now(),now()),
                    (4,'MAT-D','Delta cannucce','delta cannucce','Materiali','Pz',false,true,1,now(),now()),
                    (5,'MAT-E','Epsilon escluso','epsilon escluso','Materiali','Pz',false,true,1,now(),now());
                insert into skus_esclusi(id,sku_interno,created_at) values (1,'MAT-E',now());
                insert into xml_raw(id,payload,hash_idempotenza,source,stato_ingestion,data_ricezione)
                select i, '<synthetic/>', repeat(chr(96+i),64), 'upload_manuale','parsato',now()
                from generate_series(1,6) i;
                insert into fatture(
                    id,xml_raw_id,fornitore_id,location_id,tenant_id,
                    numero_documento,data_documento,data_ricezione_sdi,tipo_documento,totale_imponibile)
                values
                    (1,1,1,1,1,'F1','2026-03-01','2026-03-01','TD01',0),
                    (2,2,1,1,null,'F2','2026-03-02','2026-03-02','TD01',0),
                    (3,3,1,1,1,'F3','2026-03-03','2026-03-03','TD01',0),
                    (4,4,1,1,1,'NC4','2026-03-04','2026-03-04','TD04',0),
                    (5,5,1,3,2,'T2','2026-03-05','2026-03-05','TD01',0),
                    (6,6,1,2,1,'F6','2026-03-06','2026-03-06','TD01',0);
                insert into righe_fattura(
                    id,fattura_id,numero_linea,codice_fornitore_raw,descrizione_fornitore_raw,sku_interno,
                    prezzo_unitario_fatturato,sconto_percentuale,prezzo_netto_normalizzato,quantita,
                    unita_misura_fattura,is_omaggio,stato_matching)
                values
                    (1,1,1,'A','Alfa','MAT-A',1,0,1,10,'PZ',false,'matched'),
                    (2,1,2,'C','Gamma','MAT-C',5,0,5,1,'PZ',false,'matched'),
                    (3,1,3,'E','Epsilon','MAT-E',9,0,9,9,'PZ',false,'matched'),
                    (4,2,1,'A','Alfa','MAT-A',2,50,1,10,'PZ',false,'matched'),
                    (5,2,2,'B','Beta','MAT-B',100,0,100,1,'PZ',false,'matched'),
                    (6,2,3,'E','Epsilon','MAT-E',9,0,9,9,'PZ',false,'matched'),
                    (7,3,1,'A','Alfa','MAT-A',1,0,1,5,'PZ',false,'matched'),
                    (8,3,2,'A','Alfa omaggio','MAT-A',0,0,0,3,'PZ',true,'matched'),
                    (9,3,3,'C','Gamma','MAT-C',5,0,5,2,'PZ',false,'matched'),
                    (10,4,1,'A','Alfa reso','MAT-A',1,0,1,2,'PZ',false,'matched'),
                    (11,4,2,'C','Gamma reso','MAT-C',5,0,5,3,'PZ',false,'matched'),
                    (12,5,1,'D','Delta','MAT-D',1,0,1,1000,'PZ',false,'matched'),
                    (13,6,1,'D','Delta','MAT-D',7,0,7,1,'PZ',false,'matched');
                insert into righe_escluse_statistiche(riga_fattura_id,motivo,created_at)
                values (9,'prezzo anomalo',now());
            """)


def by_sku(rows):
    return {row["sku_interno"]: row for row in rows}


async def run() -> None:
    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    base = "/api/v1/smart-price-sheet/matrix?category=Materiali"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.get(base, headers=admin)
        check("matrice per nome", response.status_code == 200)
        body = response.json()
        check("sort=nome invariato", [r["sku_interno"] for r in body["rows"]] == ["MAT-A", "MAT-B", "MAT-D", "MAT-E", "MAT-C"])
        rows = by_sku(body["rows"])
        # A: F1 10 + F2 10x2x50% + F3 5 - NC4 2; omaggio non conta; F2 senza tenant = tenant 1.
        check("acquisti A", rows["MAT-A"]["acquisti"] == 3 and rows["MAT-A"]["spesa"] == "23.00")
        check("ultimo acquisto A", rows["MAT-A"]["ultimo_acquisto"] == "2026-03-03")
        # C: F1 5; riga F3 esclusa; NC4 -15 in spesa ma non e' un acquisto.
        check("nota di credito e riga esclusa", rows["MAT-C"]["acquisti"] == 1 and rows["MAT-C"]["spesa"] == "-10.00")
        check("ultimo acquisto C", rows["MAT-C"]["ultimo_acquisto"] == "2026-03-01")
        check("altro tenant escluso", rows["MAT-D"]["acquisti"] == 1 and rows["MAT-D"]["spesa"] == "7.00")
        check("sku escluso", rows["MAT-E"]["acquisti"] == 0 and rows["MAT-E"]["ultimo_acquisto"] is None)

        response = await client.get(f"{base}&sort=acquisti", headers=admin)
        check("sort=acquisti", [r["sku_interno"] for r in response.json()["rows"]] == ["MAT-A", "MAT-B", "MAT-D", "MAT-C", "MAT-E"])
        response = await client.get(f"{base}&sort=spesa", headers=admin)
        check("sort=spesa", [r["sku_interno"] for r in response.json()["rows"]] == ["MAT-B", "MAT-A", "MAT-D", "MAT-E", "MAT-C"])

        first = (await client.get(f"{base}&sort=acquisti&limit=2", headers=admin)).json()
        second = (await client.get(f"{base}&sort=acquisti&limit=2&offset=2", headers=admin)).json()
        check("ordinamento prima della paginazione",
              [r["sku_interno"] for r in first["rows"]] == ["MAT-A", "MAT-B"]
              and [r["sku_interno"] for r in second["rows"]] == ["MAT-D", "MAT-C"]
              and first["total"] == 5)

        response = await client.get(f"{base}&sort=acquisti&location_id=2", headers=admin)
        located = response.json()["rows"]
        check("filtro sede", [r["sku_interno"] for r in located][:2] == ["MAT-D", "MAT-A"]
              and by_sku(located)["MAT-A"]["acquisti"] == 0)

        response = await client.get(f"{base}&sort=acquisti&periodo=12m", headers=admin)
        check("periodo 12 mesi", response.status_code == 200 and response.json()["periodo"] == "12m")
        response = await client.get(f"{base}&sort=prezzo", headers=admin)
        check("sort non valido rifiutato", response.status_code == 422)


if __name__ == "__main__":
    asyncio.run(run())
