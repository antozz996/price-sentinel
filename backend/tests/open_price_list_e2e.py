"""E2E su database usa e getta: listino aperto (link fisso) e date del modulo prezzi.

Copre i casi trovati nella revisione del 26/11/2026:
- due ribassi nello stesso giorno: resta un solo prezzo valido oggi (correzione sulla riga);
- pagina aperta prima di un cambio di riga: l'invio si aggancia alla riga attuale dell'offerta;
- modulo prezzi: data di inizio fuori limite rifiutata; data non successiva al prezzo attuale
  spostata al giorno dopo invece di bloccare l'approvazione.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

import httpx
import psycopg2

from app.main import app
from app.services.auth import create_access_token

DSN = os.environ["TEST_DATABASE_DSN"]
TODAY = datetime.now(ZoneInfo("Europe/Rome")).date()


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def sql(query: str, *params):
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall() if cursor.description else None


def seed() -> None:
    sql("""
        insert into location(id,nome_struttura,piva_riferimento,tipologia,tenant_id)
        values (1,'Open list CI venue','00000000001','ristorante',1);
        insert into utenti(id,email,password_hash,ruolo,ruolo_dettagliato,location_id,tenant_id,attivo,
                           settore_abilitato,refresh_token_version)
        values (1,'open-list-admin@test.local','x','admin','admin',null,1,true,'all',1);
        insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
        values (1,'10000000001','Open list CI supplier',true);
        insert into products(id,sku_interno,canonical_name,normalized_name,category,comparison_unit,
                             is_commodity,is_active,unit_count,created_at,updated_at)
        values (1,'OPL-1','Prodotto sintetico','prodotto sintetico','Beverage','Pz',false,true,1,now(),now());
        insert into supplier_product_aliases(id,supplier_id,product_id,supplier_code,raw_description,
               normalized_description,status,confidence_score,source,first_seen_at,last_seen_at,created_at,updated_at)
        values (1,1,1,'OPL-1-A','Prodotto sintetico','prodotto sintetico','approved',1,'manual',now(),now(),now(),now());
        insert into supplier_category_capabilities
            (supplier_id, category, enabled, reason, created_by, updated_by, created_at, updated_at)
        values (1, 'Beverage', true, 'Synthetic CI', 1, 1, now(), now());
        select setval(pg_get_serial_sequence('fornitori','id'), 1);
        select setval(pg_get_serial_sequence('products','id'), 1);
        select setval(pg_get_serial_sequence('supplier_product_aliases','id'), 1);
    """)
    sql("""insert into listino_master(id,fornitore_id,sku_interno,descrizione,prezzo_pattuito,unita_misura,
               data_inizio_validita,supplier_product_alias_id,origine)
           values (1,1,'OPL-1','Prodotto sintetico',10,'Pz',%s,1,'manuale');
           select setval(pg_get_serial_sequence('listino_master','id'), 1);""", TODAY - timedelta(days=30))


def active_rows():
    return sql("""select id, prezzo_pattuito, data_inizio_validita from listino_master
                  where fornitore_id=1 and data_inizio_validita <= %s
                    and (data_scadenza is null or data_scadenza >= %s) order by id""", TODAY, TODAY)


async def run() -> None:
    seed()
    admin = {"Authorization": f"Bearer {create_access_token(1, 'admin')}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver", timeout=20) as c:
        made = await c.post("/api/v1/supplier-price-links/supplier/1", headers=admin)
        check("admin creates the fixed link", made.status_code == 200 and made.json()["link"]["path"])
        token = made.json()["link"]["path"].rsplit("/", 1)[1]
        base = f"/api/v1/supplier-price-links/public/{token}"

        page = (await c.get(base)).json()
        check("supplier sees the offer with its stable key", [(i["listino_id"], i["chiave"]) for i in page["items"]] == [(1, "OPL-1#1")])

        first = await c.post(f"{base}/submit", json={"modifiche": [{"listino_id": 1, "prezzo": "9"}]})
        check("a decrease is accepted", first.status_code == 200 and first.json()["riepilogo"]["ribassi"] == 1)
        rows = active_rows()
        check("the decrease is in the price list today", len(rows) == 1 and float(rows[0][1]) == 9.0 and rows[0][2] == TODAY)
        new_id = rows[0][0]

        # Pagina vecchia (riga 1) e seconda correzione nello stesso giorno.
        second = await c.post(f"{base}/submit", json={"modifiche": [{"listino_id": 1, "prezzo": "8"}]})
        body = second.json()
        check("a stale page is matched to the current row", second.status_code == 200 and body["riepilogo"]["saltati"] == [])
        rows = active_rows()
        check("a same-day correction leaves one price valid today", len(rows) == 1 and rows[0][0] == new_id and float(rows[0][1]) == 8.0)

        third = await c.post(f"{base}/submit", json={"modifiche": [{"listino_id": new_id, "prezzo": "7.5"}]})
        rows = active_rows()
        check("correcting again from the current row also stays on one row",
              third.status_code == 200 and len(rows) == 1 and float(rows[0][1]) == 7.5)

        gone = await c.post(f"{base}/submit", json={"modifiche": [{"listino_id": 999999, "prezzo": "5"}]})
        check("an unknown row is reported, not a whole-batch error",
              gone.status_code == 200 and gone.json()["riepilogo"]["saltati"] == ["riga 999999"])

        confirmed = await c.post(f"{base}/confirm-unchanged")
        check("confirm unchanged works", confirmed.status_code == 200)

        # Modulo prezzi sulla riga attuale.
        form = await c.post("/api/v1/supplier-price-forms/", headers=admin, json={
            "supplier_id": 1, "request_type": "confirmation", "listino_ids": [new_id], "expires_in_days": 7})
        check("admin creates a confirmation form", form.status_code == 201)
        ftoken, item = form.json()["token"], form.json()["request"]["items"][0]
        fbase = f"/api/v1/supplier-price-forms/public/{ftoken}"
        public = (await c.get(fbase)).json()
        check("the form exposes the accepted start-date range",
              public["validita_min"] == (TODAY - timedelta(days=31)).isoformat()
              and public["validita_max"] == (TODAY + timedelta(days=120)).isoformat())
        answer = {"item_id": item["id"], "non_trattato": False, "offerte": [{
            "prezzo": "7.0000", "unita_misura": item["unita_corrente"] or "PZ", "quantita_confezione": "1",
            "dicitura_fornitore": "Prodotto sintetico", "conferma_prezzo": False}]}
        wrong_year = await c.post(f"{fbase}/submit", json={
            "validita_inviata_da": (TODAY - timedelta(days=365)).isoformat(), "answers": [answer]})
        check("a start date a year ago is refused", wrong_year.status_code == 422 and "anno" in wrong_year.json()["detail"])
        sent = await c.post(f"{fbase}/submit", json={"validita_inviata_da": TODAY.isoformat(), "answers": [answer]})
        check("a start date equal to the current price is accepted from the supplier", sent.status_code == 200)
        approved = await c.post(f"/api/v1/supplier-price-forms/{form.json()['request']['id']}/approve", headers=admin)
        result = approved.json()
        check("approval moves the start to the day after the current price instead of failing",
              approved.status_code == 200 and result["decorrenza_spostata"] is True
              and result["decorrenza"] == (TODAY + timedelta(days=1)).isoformat())
        rows = active_rows()
        check("today the corrected price is still the only valid one", len(rows) == 1 and float(rows[0][1]) == 7.5)
        tomorrow = sql("""select prezzo_pattuito from listino_master where fornitore_id=1 and data_inizio_validita=%s""",
                       TODAY + timedelta(days=1))
        check("the approved price starts tomorrow", [float(r[0]) for r in tomorrow] == [7.0])


if __name__ == "__main__":
    asyncio.run(run())
