"""E2E tests for the read-only purchase volume analysis (disposable CI DB only).

Covers invoice and order sources, unit handling (never summing different
units), tenant isolation, admin-only access, filters, detail and CSV export.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import httpx
import psycopg2

from app.api.v1.purchase_volumes import conversion_factor
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
                values (1,'Volumi CI venue A','00000000001','ristorante',1),
                       (2,'Volumi CI venue B','00000000002','ristorante',2);
                insert into utenti(id,email,password_hash,ruolo,location_id,tenant_id,attivo,refresh_token_version)
                values (1,'volumi-admin-a@test.local','x','admin',null,1,true,1),
                       (2,'volumi-manager-a@test.local','x','manager',1,1,true,1),
                       (3,'volumi-admin-b@test.local','x','admin',null,2,true,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Fornitore Alfa CI',true),
                       (2,'10000000002','Fornitore Beta CI',true);
                insert into products(id,sku_interno,canonical_name,normalized_name,category,subcategory,
                                     comparison_unit,is_commodity,is_active,unit_count,created_at,updated_at)
                values (1,'CI-ACQUA','Acqua naturale CI','acqua naturale ci','Beverage','Acqua',
                        'Pz',false,true,1,now(),now()),
                       (2,'CI-FRAGOLE','Fragole CI','fragole ci','Frutta','Fresca',
                        'Kg',false,true,1,now(),now());
                -- Supplier Alfa sells the water in cartons of 6: the alias makes the conversion reliable.
                insert into supplier_product_aliases(id,supplier_id,product_id,supplier_code,raw_description,
                    normalized_description,pack_qty,status,confidence_score,source,
                    first_seen_at,last_seen_at,created_at,updated_at)
                values (1,1,1,'ACQ-CT','ACQUA NATURALE CT 6','acqua naturale ct 6',6,'approved',1,'test',
                        now(),now(),now(),now());
                insert into xml_raw(id,payload,hash_idempotenza,source,stato_ingestion,data_ricezione)
                select i, '<synthetic/>', repeat(chr(96+i),64), 'upload_manuale','parsato',now()
                from generate_series(1,6) i;
                insert into fatture(id,xml_raw_id,fornitore_id,location_id,tenant_id,numero_documento,
                                    data_documento,data_ricezione_sdi,tipo_documento,totale_imponibile,marker)
                values (1,1,1,1,1,'A-1',current_date-2,current_date-2,'TD01',18,'nessuno'),
                       (2,2,2,1,1,'B-1',current_date-5,current_date-5,'TD01',4,'nessuno'),
                       (3,3,1,1,1,'A-NC',current_date-1,current_date-1,'TD04',3,'nessuno'),
                       (4,4,1,1,1,'A-OLD',current_date-60,current_date-60,'TD01',30,'nessuno'),
                       (5,5,1,2,2,'T2-1',current_date-2,current_date-2,'TD01',99,'nessuno'),
                       (6,6,1,1,1,'A-2',current_date-3,current_date-3,'TD01',12,'nessuno');
                insert into righe_fattura(id,fattura_id,numero_linea,codice_fornitore_raw,descrizione_fornitore_raw,
                    sku_interno,prezzo_unitario_fatturato,sconto_percentuale,prezzo_netto_normalizzato,
                    quantita,unita_misura_fattura,is_omaggio,stato_matching)
                values
                    -- 2 cartons x 6 at 3,00 = 12 pieces, spend 6
                    (1,1,1,'ACQ-CT','ACQUA NATURALE CT 6','CI-ACQUA',3,0,0.5,2,'CT',false,'matched'),
                    -- 3 kg of strawberries at 4,00
                    (2,1,2,'FRA-KG','FRAGOLE KG','CI-FRAGOLE',4,0,4,3,'KG',false,'matched'),
                    -- 10 pieces at 0,40 = 4,00 and one free piece
                    (3,2,1,'B-ACQ','ACQUA NATURALE PZ','CI-ACQUA',0.4,0,0.4,10,'PZ',false,'matched'),
                    (4,2,2,'B-ACQ','ACQUA NATURALE PZ','CI-ACQUA',0,0,0,1,'PZ',true,'matched'),
                    -- credit note, old invoice and other tenant must not be counted
                    (5,3,1,'ACQ-CT','ACQUA NATURALE CT 6','CI-ACQUA',3,0,0.5,1,'CT',false,'matched'),
                    (6,4,1,'ACQ-CT','ACQUA NATURALE CT 6','CI-ACQUA',3,0,0.5,10,'CT',false,'matched'),
                    (7,5,1,'ACQ-CT','ACQUA NATURALE CT 6','CI-ACQUA',3,0,0.5,33,'CT',false,'matched'),
                    -- strawberry trays with unknown weight: never added to kilograms
                    (8,6,1,'FRA-CF','FRAGOLE VASCHETTA','CI-FRAGOLE',6,0,6,2,'CF',false,'matched');
                insert into ordini(id,fornitore_id,location_id,user_id,tenant_id,settore,data_ordine,
                                   spesa_totale,stato,stato_ricezione)
                values (1,1,1,1,1,'Bar',now()-interval '3 days',14.5,'inviato','da_ricevere'),
                       (2,1,2,3,2,'Bar',now()-interval '3 days',29,'inviato','da_ricevere');
                insert into righe_ordine(id,ordine_id,product_id,sku_interno,descrizione,quantita,uom,
                                         prezzo_pattuito,prezzo_inserito,stato_ottimizzazione,stato_riga)
                values (1,1,1,'CI-ACQUA','Acqua naturale CI',5,'CT',2.9,2.9,'concordato','in_attesa'),
                       (2,2,1,'CI-ACQUA','Acqua naturale CI',10,'CT',2.9,2.9,'concordato','in_attesa');
            """)


def by_sku(payload: dict) -> dict:
    return {item["sku_interno"]: item for item in payload["prodotti"]}


async def run() -> None:
    piece_product = SimpleNamespace(comparison_unit="Pz", unit_count=1, volume_ml=None, weight_g=None)
    check("a carton is not converted to pieces when the pack size is unknown",
          conversion_factor("CT", piece_product, None) is None)
    check("kilograms are never converted to pieces",
          conversion_factor("KG", piece_product, None) is None)
    check("a carton of 6 becomes 6 pieces with a reliable alias",
          conversion_factor("CT", piece_product, SimpleNamespace(
              pack_qty=6, volume_ml=None, weight_g=None, raw_description="")) == 6)
    kg_product = SimpleNamespace(comparison_unit="Kg", unit_count=1, volume_ml=None, weight_g=None)
    check("a 250 g piece becomes 0,25 kg",
          conversion_factor("PZ", kg_product, SimpleNamespace(
              pack_qty=1, volume_ml=None, weight_g=250, raw_description="")) == 0.25)

    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    admin_b = {"Authorization": f"Bearer {create_access_token(3, 'admin')}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver", timeout=15,
    ) as client:
        denied = await client.get("/api/v1/volumi", headers=manager)
        check("a manager cannot open the admin volume analysis", denied.status_code == 403)
        anonymous = await client.get("/api/v1/volumi")
        check("a request without credentials is refused", anonymous.status_code in (401, 403, 422))
        forged = await client.get("/api/v1/volumi", headers={"Authorization": "Bearer not-a-token"})
        check("an invalid token cannot open the volume analysis", forged.status_code == 401)

        options = await client.get("/api/v1/volumi/opzioni", headers=admin)
        check("filter options list suppliers and categories",
              options.status_code == 200
              and {s["nome"] for s in options.json()["fornitori"]} >= {"Fornitore Alfa CI", "Fornitore Beta CI"}
              and {"nome": "Frutta", "sottocategorie": ["Fresca"]} in options.json()["categorie"])

        response = await client.get("/api/v1/volumi", headers=admin)
        check("default volume analysis responds", response.status_code == 200)
        data = response.json()
        check("default period is the last 30 days and source is invoices",
              data["fonte"] == "fatture" and data["data_da"] < data["data_a"])
        items = by_sku(data)
        acqua = items["CI-ACQUA"]
        check("cartons and pieces are converted to 23 pieces (12 + 10 + 1 free)",
              acqua["quantita_normalizzata"] == 23 and acqua["unita_normalizzata"] == "Pz")
        check("raw quantities keep their own units",
              {(q["unita"], q["quantita"]) for q in acqua["quantita_per_unita"]} == {("CT", 2), ("PZ", 11)})
        check("credit notes, old invoices and other tenants are excluded",
              acqua["righe"] == 3 and acqua["documenti"] == 2 and acqua["spesa_totale"] == 10)
        check("average price uses only paid quantity (10,00 / 22 pieces)",
              abs(acqua["prezzo_medio"] - 10 / 22) < 0.0001 and acqua["prezzo_medio_unita"] == "Pz")
        check("free goods are reported separately", acqua["quantita_omaggio"] == 1)
        suppliers = {s["nome"]: s for s in acqua["fornitori"]}
        check("breakdown by supplier keeps each supplier's quantity",
              suppliers["Fornitore Alfa CI"]["quantita_normalizzata"] == 12
              and suppliers["Fornitore Beta CI"]["quantita_normalizzata"] == 11)

        fragole = items["CI-FRAGOLE"]
        check("kilograms and trays of unknown weight are never summed",
              fragole["quantita_normalizzata"] is None
              and {(q["unita"], q["quantita"]) for q in fragole["quantita_per_unita"]} == {("KG", 3), ("CF", 2)}
              and fragole["prezzo_medio"] is None)
        check("supplier breakdown also keeps units separate",
              fragole["fornitori"][0]["quantita_normalizzata"] is None)

        older = by_sku((await client.get(
            "/api/v1/volumi", headers=admin,
            params={"data_da": "2000-01-01", "data_a": "2100-01-01"})).json())
        check("an explicit period includes older invoices",
              older["CI-ACQUA"]["quantita_normalizzata"] == 83)

        searched = (await client.get("/api/v1/volumi", headers=admin, params={"q": "fragol"})).json()
        check("product search by name", [i["sku_interno"] for i in searched["prodotti"]] == ["CI-FRAGOLE"])
        category = (await client.get("/api/v1/volumi", headers=admin,
                                     params={"categoria": "Beverage", "sottocategoria": "Acqua"})).json()
        check("category and subcategory filter", [i["sku_interno"] for i in category["prodotti"]] == ["CI-ACQUA"])
        supplier = by_sku((await client.get("/api/v1/volumi", headers=admin, params={"fornitore_id": 2})).json())
        check("supplier filter", list(supplier) == ["CI-ACQUA"]
              and supplier["CI-ACQUA"]["quantita_normalizzata"] == 11)

        bad = await client.get("/api/v1/volumi", headers=admin,
                               params={"data_da": "2026-02-01", "data_a": "2026-01-01"})
        check("an inverted period is rejected", bad.status_code == 422)

        orders = by_sku((await client.get("/api/v1/volumi", headers=admin, params={"fonte": "ordini"})).json())
        check("order source counts requested quantity of this tenant only (5 cartons = 30 pieces)",
              list(orders) == ["CI-ACQUA"]
              and orders["CI-ACQUA"]["quantita_normalizzata"] == 30
              and orders["CI-ACQUA"]["spesa_totale"] == 14.5)

        other = by_sku((await client.get("/api/v1/volumi", headers=admin_b)).json())
        check("another tenant sees only its own invoices", other["CI-ACQUA"]["quantita_normalizzata"] == 198)

        for granularity in ("settimana", "mese"):
            detail = await client.get("/api/v1/volumi/dettaglio", headers=admin,
                                      params={"sku": "CI-ACQUA", "granularita": granularity})
            periods = detail.json()["periodi"] if detail.status_code == 200 else []
            check(f"detail by {granularity} adds up to the period total",
                  detail.status_code == 200 and periods
                  and sum(p["quantita_normalizzata"] for p in periods) == 23)

        exported = await client.get("/api/v1/volumi/export.csv", headers=admin)
        body = exported.content.decode("utf-8-sig")
        check("CSV export contains products and supplier rows",
              exported.status_code == 200
              and exported.headers["content-type"].startswith("text/csv")
              and "Acqua naturale CI" in body and "Fornitore Beta CI" in body)

    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select count(*) from righe_fattura")
            check("the analysis is read-only", cursor.fetchone()[0] == 8)


if __name__ == "__main__":
    asyncio.run(run())
