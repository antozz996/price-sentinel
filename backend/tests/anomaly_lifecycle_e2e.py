"""Anomaly visibility, re-mapping and credit-note rules on disposable PostgreSQL.

Only run via run_ci_disposable_e2e.py or another throwaway database.
All suppliers, products and documents are synthetic.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import psycopg2
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from sqlalchemy import select

import app.main  # noqa: F401  (registers every model)
from app.api.deps import get_current_user
from app.api.v1.anomalie import get_anomalia, list_anomalie
from app.api.v1.disputes import list_dispute_candidates
from app.api.v1.fatture import ResolveActionPayload, get_fattura, list_fatture, resolve_parked_line
from app.api.v1.intelligence import get_kpi, get_price_trend, get_pricing_audit, get_variance_loss
from app.api.v1.product_identity import approve_candidate
from app.database import async_session_factory
from app.models.anomalie import Anomalia, AnomaliaArchiviata, NotaDiCredito, StatoValidazione
from app.models.esclusi import RigaEsclusaStatistiche
from app.models.fatture import (
    Fattura,
    RigaFattura,
    StatoMatching,
    TipoDocumento,
    XMLRaw,
)
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import MatchCandidate, Product, SupplierProductAlias
from app.services.ingestion import _process_td04
from app.services.normalization import normalize_text

DSN = os.environ["TEST_DATABASE_DSN"]
ADMIN = SimpleNamespace(id=1, ruolo=SimpleNamespace(value="admin"), location_id=None, tenant_id=1)
DOC_DATE = date(2026, 10, 10)
AGREED_PRICE = Decimal("10.00")


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS: {name}", flush=True)


def seed_masters() -> None:
    with psycopg2.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                insert into location(id, nome_struttura, piva_riferimento, tipologia)
                values (1, 'Struttura Sintetica CI', '00000000001', 'ristorante');
                insert into utenti(id,email,password_hash,ruolo,location_id,attivo,refresh_token_version)
                values (1,'admin@test.local','x','admin',null,true,1);
                insert into fornitori(id,partita_iva,nome_azienda,attivo_whitelist)
                values (1,'10000000001','Fornitore Sintetico CI',true);
            """)


class Fixture:
    def __init__(self, db) -> None:
        self.db = db
        self.next_line = 1
        self.fattura: Fattura | None = None

    async def xml(self, key: str) -> XMLRaw:
        xml = XMLRaw(
            payload="<synthetic/>",
            hash_idempotenza=f"ci-{key}",
            data_ricezione=datetime.now(timezone.utc),
        )
        self.db.add(xml)
        await self.db.flush()
        return xml

    async def invoice(self) -> Fattura:
        xml = await self.xml("td01")
        self.fattura = Fattura(
            xml_raw_id=xml.id,
            fornitore_id=1,
            location_id=1,
            numero_documento="CI-SYNTH-0001",
            data_documento=DOC_DATE,
            data_ricezione_sdi=DOC_DATE,
            tipo_documento=TipoDocumento.TD01,
            totale_imponibile=Decimal("100.00"),
            tenant_id=1,
        )
        self.db.add(self.fattura)
        await self.db.flush()
        return self.fattura

    async def product(self, sku: str, *, listed: bool = True) -> Product:
        product = Product(
            sku_interno=sku,
            canonical_name=f"Prodotto sintetico {sku}",
            normalized_name=normalize_text(f"Prodotto sintetico {sku}"),
            comparison_unit="piece",
            is_active=True,
        )
        self.db.add(product)
        if listed:
            self.db.add(
                ListinoMaster(
                    fornitore_id=1,
                    sku_interno=sku,
                    descrizione=f"Listino sintetico {sku}",
                    prezzo_pattuito=AGREED_PRICE,
                    unita_misura="Pz",
                    data_inizio_validita=date(2026, 1, 1),
                )
            )
        await self.db.flush()
        return product

    async def line(self, code: str, price: str, sku: str | None = "OLD") -> RigaFattura:
        line = RigaFattura(
            fattura_id=self.fattura.id,
            numero_linea=self.next_line,
            codice_fornitore_raw=code,
            descrizione_fornitore_raw=f"Descrizione sintetica {code}",
            sku_interno=sku,
            prezzo_unitario_fatturato=Decimal(price),
            prezzo_netto_normalizzato=Decimal(price),
            quantita=Decimal("1"),
            unita_misura_fattura="PZ",
            stato_matching=StatoMatching.matched,
        )
        self.next_line += 1
        self.db.add(line)
        await self.db.flush()
        return line

    async def anomaly(self, line: RigaFattura, delta: str, state: StatoValidazione) -> Anomalia:
        anomaly = Anomalia(
            riga_fattura_id=line.id,
            delta_prezzo=Decimal(delta),
            delta_totale=Decimal(delta),
            prezzo_listino_snapshot=AGREED_PRICE,
            prezzo_fatturato_snapshot=AGREED_PRICE + Decimal(delta),
            stato_validazione=state,
        )
        self.db.add(anomaly)
        await self.db.flush()
        return anomaly

    async def line_with_anomaly(self, code: str, delta: str, state: StatoValidazione) -> tuple[RigaFattura, Anomalia]:
        line = await self.line(code, str(AGREED_PRICE + Decimal(delta)))
        return line, await self.anomaly(line, delta, state)


async def anomaly_of(line_id: int) -> Anomalia | None:
    async with async_session_factory() as db:
        return await db.scalar(select(Anomalia).where(Anomalia.riga_fattura_id == line_id))


async def resolve(line_id: int, product_id: int) -> None:
    async with async_session_factory() as db:
        await resolve_parked_line(
            line_id,
            ResolveActionPayload(action="associate_existing", product_id=product_id),
            current_user=ADMIN,
            db=db,
        )
        await db.commit()


async def check_visibility() -> tuple[int, int, int]:
    async with async_session_factory() as db:
        fx = Fixture(db)
        await fx.invoice()
        await fx.product("OLD", listed=False)
        _, hidden_unworked = await fx.line_with_anomaly("MICRO-OPEN", "0.05", StatoValidazione.da_verificare)
        _, hidden_parked = await fx.line_with_anomaly("MICRO-PARK", "0.06", StatoValidazione.in_parking)
        _, hidden_closed = await fx.line_with_anomaly("MICRO-DONE", "0.07", StatoValidazione.risolta)
        _, open_claim = await fx.line_with_anomaly("MICRO-CLAIM", "0.08", StatoValidazione.in_reclamo)
        _, open_dispute = await fx.line_with_anomaly("MICRO-DISPUTE", "0.09", StatoValidazione.contestata)
        _, open_proposal = await fx.line_with_anomaly("MICRO-PROPOSAL", "0.04", StatoValidazione.proposta_aggiornamento)
        _, material = await fx.line_with_anomaly("MATERIAL", "2.00", StatoValidazione.da_verificare)
        await db.commit()
        ids = SimpleNamespace(
            hidden={hidden_unworked.id, hidden_parked.id, hidden_closed.id},
            visible={open_claim.id, open_dispute.id, open_proposal.id, material.id},
        )
        result = (hidden_unworked.id, open_claim.id, material.id)

    async with async_session_factory() as db:
        rows = await list_anomalie(response=Response(), stato=None, limit=200, offset=0, current_user=ADMIN, db=db)
        listed = {row.id for row in rows}
        check("list hides unworked and closed micro-anomalies", not (listed & ids.hidden))
        check("list keeps open micro-anomalies and material ones", ids.visible <= listed)

        invoice_response = Response()
        invoices = await list_fatture(
            response=invoice_response, location_id=None, fornitore_id=None, tipo_documento=None, marker=None,
            data_da=None, data_a=None, search=None, limit=5, offset=0, current_user=ADMIN, db=db,
        )
        count = invoices[0]["n_anomalie"] if isinstance(invoices[0], dict) else invoices[0].n_anomalie
        check("invoice list counts only operational anomalies", count == len(ids.visible))
        check("invoice totals count only operational anomalies", invoice_response.headers["X-Total-Anomalies"] == str(len(ids.visible)))
        check("invoice totals sum the filtered invoices", Decimal(invoice_response.headers["X-Total-Amount"]) == Decimal("100.00"))

        searched_response = Response()
        await list_fatture(
            response=searched_response, location_id=None, fornitore_id=None, tipo_documento=None, marker=None,
            data_da=None, data_a=None, search="MICRO", limit=1, offset=0, current_user=ADMIN, db=db,
        )
        check(
            "invoice totals count a searched invoice once",
            Decimal(searched_response.headers["X-Total-Amount"]) == Decimal("100.00")
            and searched_response.headers["X-Total-Count"] == "1",
        )

        empty_response = Response()
        await list_fatture(
            response=empty_response, location_id=None, fornitore_id=None, tipo_documento=None, marker=None,
            data_da=None, data_a=None, search="NESSUN-RISULTATO", limit=5, offset=0, current_user=ADMIN, db=db,
        )
        check(
            "invoice totals are zero when nothing matches",
            Decimal(empty_response.headers["X-Total-Amount"]) == 0 and empty_response.headers["X-Total-Anomalies"] == "0",
        )

        kpi = await get_kpi(db=db, _admin=ADMIN)
        check("KPI waiting amount excludes micro-anomalies", Decimal(str(kpi["euro_attesa_manager"])) == Decimal("2.00"))
        check("KPI claim amount keeps an open micro-claim", Decimal(str(kpi["euro_in_contestazione"])) == Decimal("0.08"))
        check("KPI risk amount keeps an open micro-dispute", Decimal(str(kpi["euro_a_rischio"])) == Decimal("0.09"))

        candidates = await list_dispute_candidates(
            source="legacy", location_id=None, supplier_id=None, limit=200, user=ADMIN, db=db,
        )
        candidate_ids = {row["id"] for row in candidates}
        check("dispute candidates hide unworked micro-anomalies", not (candidate_ids & ids.hidden))
        check("dispute candidates keep material anomalies", material.id in candidate_ids)
    return result


async def check_remapping() -> None:
    async with async_session_factory() as db:
        fx = Fixture(db)
        fx.fattura = await db.scalar(select(Fattura).where(Fattura.numero_documento == "CI-SYNTH-0001"))
        fx.next_line = 100
        target = await fx.product("TARGET")
        stale, _ = await fx.line_with_anomaly("STALE", "0.00", StatoValidazione.da_verificare)
        parked, _ = await fx.line_with_anomaly("PARKED", "0.03", StatoValidazione.in_parking)
        worked, worked_anomaly = await fx.line_with_anomaly("WORKED", "0.02", StatoValidazione.contestata)
        material = await fx.line("REPRICED", "13.00")
        await fx.anomaly(material, "1.00", StatoValidazione.da_verificare)
        # An alias already linked to this supplier code exercises the alias re-use branch.
        db.add(
            SupplierProductAlias(
                supplier_id=1,
                product_id=target.id,
                supplier_code="PARKED",
                raw_description="Descrizione sintetica PARKED",
                normalized_description=normalize_text("Descrizione sintetica PARKED"),
                source="manual",
            )
        )
        await db.commit()
        target_id = target.id
        stale_id, parked_id, worked_id, material_id = stale.id, parked.id, worked.id, material.id
        worked_anomaly_id = worked_anomaly.id

    await resolve(stale_id, target_id)
    check("re-mapping below threshold clears an untouched anomaly", await anomaly_of(stale_id) is None)

    await resolve(parked_id, target_id)
    check("re-using an existing alias works and clears a parked anomaly", await anomaly_of(parked_id) is None)

    await resolve(worked_id, target_id)
    kept = await anomaly_of(worked_id)
    check(
        "re-mapping keeps an anomaly someone is handling",
        kept is not None and kept.id == worked_anomaly_id and kept.stato_validazione == StatoValidazione.contestata,
    )

    await resolve(material_id, target_id)
    repriced = await anomaly_of(material_id)
    check(
        "re-mapping above threshold records the new delta",
        repriced is not None and Decimal(str(repriced.delta_totale)) == Decimal("3.00"),
    )

    async with async_session_factory() as db:
        archived = {(row.riga_fattura_id, row.motivo): row for row in await db.scalars(select(AnomaliaArchiviata))}
    check("a cleared untouched anomaly is archived", (stale_id, "riassociazione_sotto_soglia") in archived)
    check("a cleared parked anomaly is archived", (parked_id, "riassociazione_sotto_soglia") in archived)
    replaced = archived.get((material_id, "riassociazione"))
    check(
        "a replaced anomaly keeps its previous values in the archive",
        replaced is not None
        and replaced.stato_validazione == "da_verificare"
        and Decimal(replaced.snapshot["delta_totale"]) == Decimal("1.00"),
    )
    check("an anomaly someone is handling is never archived by re-mapping", all(line != worked_id for line, _ in archived))


async def check_candidate_approval() -> None:
    async with async_session_factory() as db:
        fx = Fixture(db)
        fx.fattura = await db.scalar(select(Fattura).where(Fattura.numero_documento == "CI-SYNTH-0001"))
        fx.next_line = 200
        target = await db.scalar(select(Product).where(Product.sku_interno == "TARGET"))
        line, _ = await fx.line_with_anomaly("CANDIDATE", "0.00", StatoValidazione.da_verificare)
        candidate = MatchCandidate(
            invoice_line_id=line.id,
            supplier_id=1,
            product_id=target.id,
            raw_description=line.descrizione_fornitore_raw,
            score=Decimal("95.00"),
        )
        db.add(candidate)
        await db.commit()
        candidate_id, line_id = candidate.id, line.id

    async with async_session_factory() as db:
        await approve_candidate(candidate_id, db=db, _admin=ADMIN)
        await db.commit()
    check("approving a match below threshold clears an untouched anomaly", await anomaly_of(line_id) is None)


async def check_credit_note(micro_open_id: int, micro_claim_id: int, material_id: int) -> None:
    def credit_line(number: int, code: str) -> SimpleNamespace:
        return SimpleNamespace(
            numero_linea=number,
            codice_articolo=code,
            tipo_codice="FORNITORE",
            descrizione=f"Descrizione sintetica {code}",
            prezzo_unitario=Decimal("1.00"),
            sconto_percentuale=Decimal("0"),
            prezzo_netto_normalizzato=Decimal("1.00"),
            quantita=Decimal("1"),
            unita_misura="PZ",
            aliquota_iva=Decimal("22"),
            is_omaggio=False,
        )

    parsed = SimpleNamespace(
        numero_documento="CI-SYNTH-NC-1",
        data_documento="2026-10-20",
        data_ricezione_sdi="2026-10-20",
        totale_imponibile=Decimal("3.00"),
        righe=[credit_line(1, "MICRO-OPEN"), credit_line(2, "MICRO-CLAIM"), credit_line(3, "MATERIAL")],
    )
    async with async_session_factory() as db:
        xml = await Fixture(db).xml("td04")
        fornitore = await db.get(Fornitore, 1)
        location = await db.get(Location, 1)
        result = await _process_td04(db, xml.id, parsed, fornitore, location)
        await db.commit()
    check("credit note reconciles exactly the claim and the material anomaly", result["anomalie_riconciliate"] == 2)

    async with async_session_factory() as db:
        states = {
            row.id: row.stato_validazione
            for row in await db.scalars(
                select(Anomalia).where(Anomalia.id.in_([micro_open_id, micro_claim_id, material_id]))
            )
        }
        credited = set(await db.scalars(select(NotaDiCredito.anomalia_id)))
    check("credit note ignores unworked rounding noise", states[micro_open_id] == StatoValidazione.da_verificare)
    check("credit note closes an open micro-claim", states[micro_claim_id] == StatoValidazione.risolta)
    check("credit note closes a material anomaly", states[material_id] == StatoValidazione.risolta)
    check("credit records match the closed anomalies", credited == {micro_claim_id, material_id})


async def check_variance_counts_each_line_once() -> None:
    async with async_session_factory() as db:
        fx = Fixture(db)
        fx.fattura = await db.scalar(select(Fattura).where(Fattura.numero_documento == "CI-SYNTH-0001"))
        fx.next_line = 300
        await fx.product("MULTI-SUPPLIER")
        db.add(Fornitore(id=2, partita_iva="10000000002", nome_azienda="Secondo Fornitore CI", attivo_whitelist=True))
        await db.flush()
        db.add(
            ListinoMaster(
                fornitore_id=2,
                sku_interno="MULTI-SUPPLIER",
                descrizione="Listino sintetico secondo fornitore",
                prezzo_pattuito=AGREED_PRICE,
                unita_misura="Pz",
                data_inizio_validita=date(2026, 1, 1),
            )
        )
        await fx.line("VARIANCE-LOW", "10.00", sku="MULTI-SUPPLIER")
        await fx.line("VARIANCE-HIGH", "12.00", sku="MULTI-SUPPLIER")
        await db.commit()

    async with async_session_factory() as db:
        rows = await get_variance_loss(_admin=ADMIN, db=db)
    row = next(item for item in rows if item["sku_interno"] == "MULTI-SUPPLIER")
    check("variance counts each invoice line once", row["numero_acquisti"] == 2)
    check("variance is not multiplied by active price lists", Decimal(str(row["spreco_totale"])) == Decimal("2.0"))


async def check_excluded_lines_do_not_set_reference_price() -> None:
    async with async_session_factory() as db:
        fx = Fixture(db)
        fx.fattura = await db.scalar(select(Fattura).where(Fattura.numero_documento == "CI-SYNTH-0001"))
        fx.next_line = 400
        await fx.product("OUTLIER")
        await fx.line("OUTLIER-A", "10.00", sku="OUTLIER")
        await fx.line("OUTLIER-B", "12.00", sku="OUTLIER")
        billing_error = await fx.line("OUTLIER-ERROR", "5.00", sku="OUTLIER")
        db.add(RigaEsclusaStatistiche(riga_fattura_id=billing_error.id, motivo="Errore di fatturazione (test)"))
        await db.commit()

    async with async_session_factory() as db:
        rows = await get_variance_loss(_admin=ADMIN, db=db)
    row = next(item for item in rows if item["sku_interno"] == "OUTLIER")
    check("an excluded line does not become the reference price", Decimal(str(row["prezzo_minimo"])) == Decimal("10.0"))
    check("waste is measured against the real reference price", Decimal(str(row["spreco_totale"])) == Decimal("2.0"))
    check("an excluded line still counts as a purchase", row["numero_acquisti"] == 3)


async def check_price_history_endpoints() -> None:
    async with async_session_factory() as db:
        trend = await get_price_trend("OUTLIER", _user=ADMIN, db=db)
        check("product price history opens", trend is not None)
        audit = await get_pricing_audit(location_id=None, anno=None, soglia=5.0, limit=10, offset=0, _admin=ADMIN, db=db)
        check("pricing audit works without filters", isinstance(audit, dict))


def check_cors_exposes_pagination_total() -> None:
    cors = next(item for item in app.main.app.user_middleware if item.cls is CORSMiddleware)
    options = getattr(cors, "kwargs", None) or getattr(cors, "options", {})
    check("cross-origin frontend can read the pagination total", "X-Total-Count" in options.get("expose_headers", []))


async def check_large_responses_are_compressed() -> None:
    app.main.app.dependency_overrides[get_current_user] = lambda: ADMIN
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.main.app), base_url="https://testserver"
        ) as client:
            response = await client.get("/api/v1/products", headers={"Accept-Encoding": "gzip"})
    finally:
        app.main.app.dependency_overrides.pop(get_current_user, None)
    check("large API responses are compressed", response.status_code == 200 and response.headers.get("content-encoding") == "gzip")
    check("compressed responses still decode", isinstance(response.json(), list) and len(response.json()) > 0)


async def is_hidden_from(user, call) -> bool:
    try:
        await call(user)
    except HTTPException as error:
        return error.status_code == 404
    return False


async def check_tenant_isolation() -> None:
    other_admin = SimpleNamespace(id=1, ruolo=SimpleNamespace(value="admin"), location_id=None, tenant_id=2)
    async with async_session_factory() as db:
        fx = Fixture(db)
        xml = await fx.xml("tenant-2")
        fx.fattura = Fattura(
            xml_raw_id=xml.id,
            fornitore_id=1,
            location_id=1,
            numero_documento="CI-SYNTH-TENANT-2",
            data_documento=DOC_DATE,
            data_ricezione_sdi=DOC_DATE,
            tipo_documento=TipoDocumento.TD01,
            totale_imponibile=Decimal("50.00"),
            tenant_id=2,
        )
        db.add(fx.fattura)
        await db.flush()
        _, anomaly = await fx.line_with_anomaly("OTHER-TENANT", "5.00", StatoValidazione.da_verificare)
        await db.commit()
        anomaly_id, invoice_id = anomaly.id, fx.fattura.id

    async with async_session_factory() as db:
        rows = await list_anomalie(response=Response(), stato=None, limit=200, offset=0, current_user=ADMIN, db=db)
        check("anomaly list hides another tenant", anomaly_id not in {row.id for row in rows})
        rows = await list_anomalie(response=Response(), stato=None, limit=200, offset=0, current_user=other_admin, db=db)
        check("anomaly list shows the tenant's own records", {row.id for row in rows} == {anomaly_id})
        candidates = await list_dispute_candidates(
            source="legacy", location_id=None, supplier_id=None, limit=200, user=ADMIN, db=db,
        )
        check("dispute candidates hide another tenant", anomaly_id not in {row["id"] for row in candidates})
        check(
            "anomaly detail is not reachable across tenants",
            await is_hidden_from(ADMIN, lambda user: get_anomalia(anomaly_id, _user=user, db=db)),
        )
        check(
            "invoice detail is not reachable across tenants",
            await is_hidden_from(ADMIN, lambda user: get_fattura(invoice_id, current_user=user, db=db)),
        )
        found = await get_fattura(invoice_id, current_user=other_admin, db=db)
        check("invoice detail works inside the tenant", found.id == invoice_id)


async def run() -> None:
    check_cors_exposes_pagination_total()
    micro_open_id, micro_claim_id, material_id = await check_visibility()
    await check_remapping()
    await check_candidate_approval()
    await check_credit_note(micro_open_id, micro_claim_id, material_id)
    await check_variance_counts_each_line_once()
    await check_excluded_lines_do_not_set_reference_price()
    await check_price_history_endpoints()
    await check_large_responses_are_compressed()
    await check_tenant_isolation()


if __name__ == "__main__":
    seed_masters()
    asyncio.run(run())
    print("PASS: anomaly lifecycle E2E", flush=True)
