"""Phase 12 — synthetic purchase-to-invoice lifecycle, without external dispatch.

This E2E performs writes ONLY in an isolated disposable PostgreSQL database
created by the GitHub-hosted CI runner. Never run on live staging or V1.
Tests: contract lookup -> preventive alert -> saved order -> supplier
invoice upload -> canonical matching -> price anomaly -> tenant-scoped KPI.
No emails, WhatsApp messages, external integrations or real documents.
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

# Deliberately synthetic test entities, unlike customer/production data.
XML = """<?xml version="1.0" encoding="UTF-8"?>
<FatturaElettronica>
  <FatturaElettronicaHeader>
    <DatiTrasmissione><DataOraRicezione>2026-10-10</DataOraRicezione></DatiTrasmissione>
    <CedentePrestatore><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>10000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Supplier CI Synthetic</Denominazione></Anagrafica>
    </DatiAnagrafici></CedentePrestatore>
    <CessionarioCommittente><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Location CI Synthetic</Denominazione></Anagrafica>
    </DatiAnagrafici></CessionarioCommittente>
  </FatturaElettronicaHeader>
  <FatturaElettronicaBody>
    <DatiGenerali><DatiGeneraliDocumento>
      <TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa>
      <Data>2026-10-10</Data><Numero>CI-PURCHASE-12-01</Numero>
    </DatiGeneraliDocumento></DatiGenerali>
    <DatiBeniServizi>
      <DettaglioLinee>
        <NumeroLinea>1</NumeroLinea>
        <CodiceArticolo><CodiceTipo>FORNITORE</CodiceTipo><CodiceValore>CI-SKU-001</CodiceValore></CodiceArticolo>
        <Descrizione>Synthetic product CI</Descrizione>
        <Quantita>2.00</Quantita><UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>5.00</PrezzoUnitario><PrezzoTotale>10.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>
      <DatiRiepilogo><AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>10.00</ImponibileImporto></DatiRiepilogo>
    </DatiBeniServizi>
  </FatturaElettronicaBody>
</FatturaElettronica>
""".encode("utf-8")


def check(name: str, okay: bool) -> None:
    if not okay:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def query_one(sql: str, params: tuple = ()):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id,nome_struttura,piva_riferimento,tipologia)
                values (1,'Location CI Synthetic','00000000001','ristorante');
                insert into utenti(id,email,password_hash,ruolo,location_id,attivo,tenant_id,refresh_token_version)
                values (1,'admin@synthetic.test','x','admin',null,true,1,1),
                       (2,'manager@synthetic.test','x','manager',1,true,1,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Supplier CI Synthetic',true);
                insert into products(id,sku_interno,canonical_name,normalized_name,category,
                                     comparison_unit,is_commodity,is_active,unit_count,created_at,updated_at)
                values (1,'CI-PRODUCT-001','Synthetic product CI','synthetic product ci','food',
                        'piece',false,true,1,now(),now());
                insert into supplier_product_aliases(
                    id,supplier_id,product_id,supplier_code,raw_description,normalized_description,
                    status,confidence_score,source,first_seen_at,last_seen_at,created_at,updated_at)
                values (1,1,1,'CI-SKU-001','Synthetic product CI','synthetic product ci',
                        'approved',1,'test',now(),now(),now(),now());
                insert into listino_master(
                    id,fornitore_id,sku_interno,descrizione,prezzo_pattuito,
                    unita_misura,data_inizio_validita,supplier_product_alias_id)
                values (1,1,'CI-PRODUCT-001','Synthetic product CI',4.00,
                        'piece','2026-01-01',1);
            """)


async def run() -> None:
    # Both order write and XML ingestion must happen in the SAME disposable DB.
    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    basket = [{"sku_interno": "CI-PRODUCT-001", "quantita": 2, "prezzo_inserito": 5.0}]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        timeout=15.0,
    ) as client:
        res = await client.post("/api/v1/ordini/ottimizza", headers=manager, json=basket)
        check("manager cannot run admin purchasing optimization", res.status_code == 403)

        res = await client.post("/api/v1/ordini/ottimizza", headers=admin, json=basket)
        check("admin gets contractual purchase simulation", res.status_code == 200)
        row = res.json()["righe_ottimizzate"][0]
        check("contract supplier and net unit price identified",
              row["sku_interno"] == "CI-PRODUCT-001"
              and row["fornitore_id"] == 1
              and Decimal(str(row["prezzo_ottimale"])) == Decimal("4.0"))
        check("buyer sees price discrepancy before saving",
              row["is_anomalia"] is True and res.json()["sintesi"]["numero_anomalie"] == 1)

        res = await client.post(
            "/api/v1/ordini/crea", headers=admin,
            json={
                "location_id": 1,
                "items": [{"sku_interno": "CI-PRODUCT-001", "quantita": 2,
                           "prezzo_inserito": 4.0}],
            },
        )
        check("synthetic purchase order saved without external delivery", res.status_code == 200)
        order_ids = res.json()
        check("single supplier order stored",
              len(order_ids) == 1
              and query_one("select count(*) from ordini")[0] == 1)
        saved = query_one(
            "select o.spesa_totale, r.prezzo_pattuito, r.prezzo_inserito, r.quantita "
            "from ordini o join righe_ordine r on r.ordine_id=o.id where o.id=%s",
            (order_ids[0],),
        )
        check("saved order uses agreed net price 4 EUR x 2",
              tuple(Decimal(str(v)) for v in saved)
              == (Decimal("8.00"), Decimal("4.0000"), Decimal("4.0000"), Decimal("2.00")))
        check("no invoice exists before synthetic upload", query_one("select count(*) from fatture")[0] == 0)

        res = await client.post(
            "/api/v1/ingestion/upload", headers=admin,
            files={"files": ("ci-phase12.xml", XML, "application/xml")},
        )
        check("synthetic incoming supplier invoice accepted", res.status_code == 200)
        check("invoice parsed exactly once", res.json()["riepilogo"]["elaborati"] == 1)
        invoice = query_one(
            "select f.totale_imponibile, r.prezzo_netto_normalizzato, "
            "r.sku_interno, r.stato_matching::text "
            "from fatture f join righe_fattura r on r.fattura_id=f.id"
        )
        check("XML prices are net of VAT and canonical product matches",
              Decimal(str(invoice[0])) == Decimal("10")
              and Decimal(str(invoice[1])) == Decimal("5")
              and invoice[2] == "CI-PRODUCT-001"
              and invoice[3] == "matched")

        anomaly = query_one(
            "select delta_prezzo, delta_totale, stato_validazione::text "
            "from anomalie"
        )
        check("invoice overcharge of 1 EUR x 2 detected",
              anomaly is not None
              and Decimal(str(anomaly[0])) == Decimal("1")
              and Decimal(str(anomaly[1])) == Decimal("2")
              and anomaly[2] == "da_verificare")

        res = await client.get("/api/v1/intelligence/kpi", headers=admin)
        check("tenant-scoped dashboard exposes 2 EUR pending manager review",
              res.status_code == 200
              and Decimal(str(res.json()["euro_attesa_manager"])) == Decimal("2"))

        res = await client.post(
            "/api/v1/ingestion/upload", headers=admin,
            files={"files": ("duplicate-ci-phase12.xml", XML, "application/xml")},
        )
        check("replayed invoice leaves economic totals unchanged",
              res.status_code == 200
              and res.json()["riepilogo"]["gia_presenti"] == 1
              and query_one("select count(*) from fatture")[0] == 1
              and query_one("select count(*) from anomalie")[0] == 1)

    print(json.dumps({
        "status": "PASS",
        "scenario": "synthetic purchase-to-invoice discrepancy",
        "expected_overcharge_eur": "2.00",
        "external_dispatch": False,
    }), flush=True)


if __name__ == "__main__":
    asyncio.run(run())
