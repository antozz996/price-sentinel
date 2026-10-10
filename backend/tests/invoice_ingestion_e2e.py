"""Admin-only FatturaPA XML upload and idempotency on disposable CI PostgreSQL.

Only run via run_ci_disposable_e2e.py under GitHub-hosted temporary PostgreSQL.
All identifiers, supplier names and documents are synthetic.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token

DSN = os.environ["TEST_DATABASE_DSN"]

XML = """<?xml version="1.0" encoding="UTF-8"?>
<FatturaElettronica>
  <FatturaElettronicaHeader>
    <DatiTrasmissione><DataOraRicezione>2026-10-10</DataOraRicezione></DatiTrasmissione>
    <CedentePrestatore><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>10000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Fornitore Sintetico CI</Denominazione></Anagrafica>
    </DatiAnagrafici></CedentePrestatore>
    <CessionarioCommittente><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Struttura Sintetica CI</Denominazione></Anagrafica>
    </DatiAnagrafici></CessionarioCommittente>
  </FatturaElettronicaHeader>
  <FatturaElettronicaBody>
    <DatiGenerali><DatiGeneraliDocumento>
      <TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa>
      <Data>2026-10-10</Data><Numero>CI-SYNTH-0001</Numero>
    </DatiGeneraliDocumento></DatiGenerali>
    <DatiBeniServizi>
      <DettaglioLinee>
        <NumeroLinea>1</NumeroLinea><CodiceArticolo>
          <CodiceTipo>FORNITORE</CodiceTipo><CodiceValore>CI-SKU-001</CodiceValore>
        </CodiceArticolo>
        <Descrizione>Acqua sintetica CI</Descrizione>
        <Quantita>2.00</Quantita><UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>5.00</PrezzoUnitario><PrezzoTotale>10.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>
      <DatiRiepilogo>
        <AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>10.00</ImponibileImporto>
      </DatiRiepilogo>
    </DatiBeniServizi>
  </FatturaElettronicaBody>
</FatturaElettronica>
""".encode("utf-8")


def scalar(sql: str):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()[0]


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def seed() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id, nome_struttura, piva_riferimento, tipologia)
                values (1, 'Struttura Sintetica CI', '00000000001', 'ristorante');
                insert into utenti(id,email,password_hash,ruolo,location_id,attivo,refresh_token_version)
                values
                (1,'admin@test.local','x','admin',null,true,1),
                (2,'manager@test.local','x','manager',1,true,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Fornitore Sintetico CI',true);
            """)


async def run() -> None:
    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    manager = {"Authorization": f"Bearer {create_access_token(2, 'manager')}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        upload = lambda data: {"files": ("synthetic.xml", data, "application/xml")}

        response = await client.post("/api/v1/ingestion/upload", headers=manager, files=upload(XML))
        check("manager cannot import invoices", response.status_code == 403)
        check("manager upload did not write invoices", scalar("select count(*) from fatture") == 0)

        response = await client.post("/api/v1/ingestion/reprocess-parked", headers=manager)
        check("manager cannot reprocess stored invoices", response.status_code == 403)

        response = await client.post("/api/v1/ingestion/upload", headers=admin, files=upload(XML))
        check("synthetic FatturaPA upload accepted", response.status_code == 200)
        if response.status_code != 200:
            raise AssertionError(f"upload HTTP {response.status_code}")
        report = response.json()["riepilogo"]
        check("one invoice processed", report["elaborati"] == 1 and report["errori_formato"] == 0)
        check("exactly one invoice stored", scalar("select count(*) from fatture") == 1)
        check("one normalized line stored", scalar("select count(*) from righe_fattura") == 1)
        check(
            "net price excludes VAT",
            str(scalar("select prezzo_netto_normalizzato from righe_fattura limit 1")) == "5.0000",
        )

        response = await client.post("/api/v1/ingestion/upload", headers=admin, files=upload(XML))
        check(
            "same invoice deduplicated",
            response.status_code == 200
            and response.json()["riepilogo"]["gia_presenti"] == 1
            and scalar("select count(*) from fatture") == 1,
        )

        response = await client.post(
            "/api/v1/ingestion/upload",
            headers=admin,
            files=upload(b"<broken xml"),
        )
        check(
            "malformed XML rejected without invoice write",
            response.status_code == 200
            and response.json()["riepilogo"]["errori_formato"] == 1
            and scalar("select count(*) from fatture") == 1,
        )

        response = await client.get("/api/v1/ingestion/uploads", headers=admin)
        check("admin can read upload history", response.status_code == 200 and len(response.json()) == 3)

    print(json.dumps({"status": "PASS", "scenario": "CI synthetic XML ingestion"}), flush=True)


if __name__ == "__main__":
    asyncio.run(run())
