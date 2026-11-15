"""Contestazioni, note di credito, monitor e KPI anomalie (rapporto 14/11/2026).

Problemi coperti: M12 (candidati troncati a 200), B12 (anomalie accettate
contestabili), M13 (dashboard contestazioni con bozze e annullate), M14 (due
registri delle note di credito), M15 (un reso importato chiude l'anomalia),
B13 (monitor), B15 (KPI attesa manager con SKU esclusi), TD08 come nota di
credito. Nessun database: sessioni finte e SQL compilato per PostgreSQL.
"""
import asyncio
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

import app.models  # noqa: E402,F401  (registra tutti i modelli)
from app.api.v1 import disputes as disputes_api  # noqa: E402
from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione  # noqa: E402
from app.models.automation import AutomationAlert  # noqa: E402
from app.models.disputes import DisputeAuditEvent, DisputeCase  # noqa: E402
from app.models.fatture import Fattura, TipoDocumento  # noqa: E402
from app.models.liquidstock_integration import LiquidStockIntegrationEvent  # noqa: E402
from app.models.onboarding import LocationReconciliationSettings  # noqa: E402
from app.models.purchase_order_reconciliation import (  # noqa: E402
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
)
from app.services import automation, ingestion  # noqa: E402
from app.services import disputes as disputes_service  # noqa: E402
from app.services.anomaly_kpi import kpi_anomalies_statement, kpi_recovered_statement  # noqa: E402


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


ADMIN = SimpleNamespace(id=1, ruolo=SimpleNamespace(value="admin"), location_id=None, tenant_id=1)
MANAGER = SimpleNamespace(id=2, ruolo=SimpleNamespace(value="manager"), location_id=1, tenant_id=1)


def credit_line(numero, codice, descrizione, quantita, prezzo, sconto="0"):
    return SimpleNamespace(
        numero_linea=numero,
        codice_articolo=codice,
        tipo_codice="FORNITORE",
        descrizione=descrizione,
        prezzo_unitario=Decimal(prezzo),
        sconto_percentuale=Decimal(sconto),
        prezzo_netto_normalizzato=Decimal(prezzo),
        quantita=Decimal(quantita),
        unita_misura="BT",
        aliquota_iva=Decimal("22"),
        is_omaggio=False,
    )


def open_anomaly(anomaly_id, codice, descrizione, delta_totale, stato=StatoValidazione.da_verificare):
    return SimpleNamespace(
        id=anomaly_id,
        delta_totale=Decimal(delta_totale),
        stato_validazione=stato,
        riga_fattura=SimpleNamespace(codice_fornitore_raw=codice, descrizione_fornitore_raw=descrizione),
    )


# Caso reale: nota di credito Navas n.146 del 06/05/2026, reso di 374 BT di
# GIN TANQUERAY 100 CL a 15,1639 (5.671,30 EUR). Con il vecchio import un
# rincaro aperto sullo stesso codice veniva chiuso come "risolto".
NAVAS_146 = [
    credit_line(1, "GIN0001", "GIN TANQUERAY 100 CL", "374", "15.1639"),
    credit_line(2, None, "Spese di segreteria", "1", "0.41"),
    credit_line(3, "VODK066", "VODKA  WYBOROWA 100 CL", "48", "7.7869"),
    credit_line(4, "OMAG1", "OMAGGIO", "6", "0"),
]


class CreditNoteProposalTest(unittest.TestCase):
    """M15: un reso importato propone l'abbinamento ma non chiude nulla."""

    def test_return_of_goods_is_only_a_proposal_with_line_value_from_shared_base(self):
        tanqueray = open_anomaly(301, "GIN0001", "GIN TANQUERAY 100 CL", "1.20")
        proposals = ingestion.propose_credit_note_matches(NAVAS_146, [tanqueray])
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["anomalia_id"], 301)
        self.assertEqual(proposals[0]["abbinamento"], "codice")
        self.assertEqual(proposals[0]["valore_riga_nota"], "5671.30")
        self.assertEqual(proposals[0]["rincaro_anomalia"], "1.20")
        self.assertEqual(tanqueray.stato_validazione, StatoValidazione.da_verificare)

    def test_description_fallback_and_each_anomaly_once(self):
        by_text = open_anomaly(302, None, "VODKA  WYBOROWA 100 CL", "0.50")
        same_code = [open_anomaly(303, "GIN0001", "GIN TANQUERAY 100 CL", "2.00")]
        proposals = ingestion.propose_credit_note_matches(
            NAVAS_146 + [credit_line(5, "GIN0001", "GIN TANQUERAY 100 CL", "2", "15.1639")],
            [by_text] + same_code,
        )
        self.assertEqual([p["anomalia_id"] for p in proposals], [303, 302])
        self.assertEqual(proposals[1]["abbinamento"], "descrizione")

    def test_zero_value_line_proposes_nothing(self):
        omaggio = open_anomaly(304, "OMAG1", "OMAGGIO", "3.00")
        self.assertEqual(ingestion.propose_credit_note_matches(NAVAS_146[3:], [omaggio]), [])


class FakeIngestionSession:
    def __init__(self, anomalies):
        self.anomalies = anomalies
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, Fattura) and obj.id is None:
                obj.id = 9001

    async def execute(self, statement, *args, **kwargs):
        anomalies = self.anomalies
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(anomalies)))


def parsed_credit_note(numero="146"):
    return SimpleNamespace(
        numero_documento=numero,
        data_documento="2026-05-06",
        data_ricezione_sdi="2026-05-06",
        totale_imponibile=Decimal("5671.30"),
        righe=NAVAS_146,
    )


class ImportedCreditNoteTest(unittest.TestCase):
    def run_import(self, processor, anomalies):
        db = FakeIngestionSession(anomalies)
        no_match = SimpleNamespace(matched=False, senza_listino=False, sku_interno=None)
        with patch("app.services.matching.match_riga", AsyncMock(return_value=no_match)):
            result = asyncio.run(
                processor(db, 77, parsed_credit_note(), SimpleNamespace(id=21), SimpleNamespace(id=2))
            )
        return db, result

    def test_td04_import_closes_nothing_and_records_no_money(self):
        tanqueray = open_anomaly(301, "GIN0001", "GIN TANQUERAY 100 CL", "1.20", StatoValidazione.in_reclamo)
        db, result = self.run_import(ingestion._process_td04, [tanqueray])
        self.assertEqual(result["status"], "td04_registrata")
        self.assertEqual(result["anomalie_riconciliate"], 0)
        self.assertEqual(tanqueray.stato_validazione, StatoValidazione.in_reclamo)
        self.assertFalse([obj for obj in db.added if isinstance(obj, NotaDiCredito)])
        alerts = [obj for obj in db.added if isinstance(obj, AutomationAlert)]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, ingestion.CREDIT_NOTE_PROPOSAL_ALERT)
        self.assertEqual(alerts[0].dedupe_key, "credit_note_proposal:9001:301")
        self.assertEqual((alerts[0].status, alerts[0].location_id, alerts[0].entity_id), ("open", 2, "301"))
        self.assertNotIn(ingestion.CREDIT_NOTE_PROPOSAL_ALERT, automation.MANAGED_ALERT_TYPES)

    def test_td08_follows_the_credit_note_path(self):
        tanqueray = open_anomaly(301, "GIN0001", "GIN TANQUERAY 100 CL", "1.20")
        db, result = self.run_import(ingestion._process_td08, [tanqueray])
        fattura = next(obj for obj in db.added if isinstance(obj, Fattura))
        self.assertEqual(fattura.tipo_documento, TipoDocumento.TD08)
        self.assertEqual(result["status"], "td08_registrata")
        self.assertEqual([p["anomalia_id"] for p in result["proposte_chiusura"]], [301])
        self.assertEqual(tanqueray.stato_validazione, StatoValidazione.da_verificare)

    def test_known_non_product_check_skips_td08_too(self):
        import inspect

        source = inspect.getsource(ingestion._is_known_non_product)
        self.assertIn("notin_(CREDIT_NOTE_TYPES)", source)


class CandidatePaginationTest(unittest.TestCase):
    """M12: oggi 235 anomalie, le 35 oltre la 200esima (87,24 EUR) non erano raggiungibili."""

    def rows(self):
        base = date(2026, 11, 6)
        return [
            {"source": "legacy", "id": i, "created_at": base + timedelta(days=i % 9)}
            for i in range(1, 236)
        ]

    def test_every_candidate_is_reachable_without_repeats(self):
        seen = []
        offset = 0
        while True:
            page = disputes_api.merge_candidate_page(self.rows(), offset, 100)
            if not page:
                break
            seen.extend(item["id"] for item in page)
            offset += 100
        self.assertEqual(len(seen), 235)
        self.assertEqual(len(set(seen)), 235)

    def test_merge_order_is_stable_on_same_date(self):
        page = disputes_api.merge_candidate_page(
            [
                {"source": "legacy", "id": 5, "created_at": date(2026, 11, 10)},
                {"source": "legacy", "id": 9, "created_at": date(2026, 11, 10)},
            ],
            0,
            1,
        )
        self.assertEqual(page[0]["id"], 9)


class DisputableStatesTest(unittest.TestCase):
    """B12: anomalie accettate, con proposta di aggiornamento o risolte non sono contestabili."""

    def test_whitelist(self):
        allowed = set(disputes_service.DISPUTABLE_ANOMALY_STATES)
        self.assertNotIn(StatoValidazione.accettata, allowed)
        self.assertNotIn(StatoValidazione.proposta_aggiornamento, allowed)
        self.assertNotIn(StatoValidazione.risolta, allowed)
        self.assertIn(StatoValidazione.da_verificare, allowed)

    def test_create_case_refuses_accepted_anomaly(self):
        anomaly = SimpleNamespace(id=3, stato_validazione=StatoValidazione.accettata, delta_totale=Decimal("6"))
        row = SimpleNamespace(one_or_none=lambda: (anomaly, SimpleNamespace(), SimpleNamespace()))
        db = SimpleNamespace(execute=AsyncMock(return_value=row))
        selection = SimpleNamespace(legacy_anomaly_id=3, claimed_amount=None, reason=None)
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(disputes_service._resolve_legacy_selection(db, selection))
        self.assertEqual(caught.exception.status_code, 409)


class FakeResult:
    def __init__(self, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def one(self):
        return self._one

    def all(self):
        return self._rows


class DashboardSqlTest(unittest.TestCase):
    """M13: 'Da recuperare' solo sulle pratiche inviate e aperte; classifiche e trend senza bozze/annullate."""

    def statements(self):
        captured = []

        async def execute(statement, *args, **kwargs):
            captured.append(sql(statement))
            if len(captured) == 1:
                return FakeResult(one=(0, 0))
            if len(captured) == 2:
                return FakeResult(one=(0, 0, 0, 0, 0, 0, 0, None))
            return FakeResult(rows=[])

        db = SimpleNamespace(execute=execute)
        asyncio.run(disputes_api.dispute_dashboard(location_id=None, user=ADMIN, db=db))
        return captured

    def test_outstanding_only_on_sent_open_cases(self):
        totals = self.statements()[1]
        self.assertIn(
            "dispute_cases.status IN ('sent', 'supplier_replied', 'credit_note_expected', 'partially_recovered')",
            totals,
        )

    def test_rankings_and_trend_skip_drafts_and_cancelled(self):
        captured = self.statements()
        amounts, grouped_location, grouped_supplier, causes, trend = (
            captured[0], captured[2], captured[3], captured[4], captured[5],
        )
        self.assertIn("dispute_cases.status != 'cancelled'", amounts)
        for statement in (grouped_location, grouped_supplier, causes, trend):
            self.assertIn("dispute_cases.status NOT IN ('draft', 'cancelled')", statement)

    def test_admin_sees_only_tenant_locations(self):
        for statement in self.statements():
            self.assertIn("dispute_cases.location_id IN (SELECT location.id", statement)
            self.assertIn("location.tenant_id IS NULL", statement)


class FakeCaseSession:
    def __init__(self, anomalies):
        self.anomalies = anomalies

    async def scalars(self, statement):
        anomalies = self.anomalies
        return SimpleNamespace(all=lambda: list(anomalies))


def case_with(status, claimed, recovered, anomaly):
    row = SimpleNamespace(
        legacy_anomaly_id=anomaly.id, claimed_amount=Decimal(claimed), recovered_amount=Decimal(recovered)
    )
    return SimpleNamespace(status=status, anomalies=[row])


class LegacyRegisterSyncTest(unittest.TestCase):
    """M14: la nota registrata nella pratica aggiorna anche il registro anomalie."""

    def sync(self, status, claimed, recovered, start=StatoValidazione.in_reclamo):
        anomaly = SimpleNamespace(id=4, stato_validazione=start, gestito_at=None, gestito_da_admin_id=None)
        case = case_with(status, claimed, recovered, anomaly)
        asyncio.run(disputes_service.sync_legacy_anomalies(FakeCaseSession([anomaly]), case, ADMIN))
        return anomaly

    def test_full_recovery_resolves_anomaly(self):
        anomaly = self.sync("recovered", "3.00", "3.00")
        self.assertEqual(anomaly.stato_validazione, StatoValidazione.risolta)
        self.assertIsNotNone(anomaly.gestito_at)

    def test_partial_recovery_keeps_claim_open(self):
        self.assertEqual(self.sync("partially_recovered", "3.00", "1.00").stato_validazione, StatoValidazione.in_reclamo)

    def test_closed_case_resolves_anomaly(self):
        self.assertEqual(self.sync("closed", "3.00", "0").stato_validazione, StatoValidazione.risolta)

    def test_cancelled_case_returns_claim_to_contested(self):
        self.assertEqual(self.sync("cancelled", "3.00", "0").stato_validazione, StatoValidazione.contestata)

    def test_cancelled_draft_leaves_unworked_anomaly(self):
        anomaly = self.sync("cancelled", "3.00", "0", start=StatoValidazione.da_verificare)
        self.assertEqual(anomaly.stato_validazione, StatoValidazione.da_verificare)

    def test_td08_is_accepted_as_imported_credit_note(self):
        self.assertIn(TipoDocumento.TD08, disputes_service.CREDIT_NOTE_TYPES)
        self.assertIn(TipoDocumento.TD04, disputes_service.CREDIT_NOTE_TYPES)


class KpiSqlTest(unittest.TestCase):
    """B15 e M14: KPI con lo stesso perimetro della lista anomalie e i due registri delle NC."""

    def test_anomaly_kpi_excludes_excluded_skus_and_follows_tenant(self):
        text = sql(kpi_anomalies_statement(ADMIN))
        self.assertIn("NOT (EXISTS (SELECT * \nFROM skus_esclusi", text)
        self.assertIn("righe_fattura.sku_interno IS NULL", text)
        self.assertIn("fatture.tenant_id IS NULL", text)
        self.assertIn("LEFT OUTER JOIN dispute_case_anomalies", text)
        self.assertIn("greatest(anomalie.delta_totale - coalesce(dispute_case_anomalies.recovered_amount, 0), 0)", text)

    def test_recovered_kpi_sums_both_registers_without_double_counting(self):
        text = sql(kpi_recovered_statement(ADMIN))
        self.assertIn("sum(note_di_credito.importo_recuperato)", text)
        self.assertIn("sum(dispute_case_anomalies.recovered_amount)", text)
        self.assertIn("note_di_credito.anomalia_id = dispute_case_anomalies.legacy_anomaly_id", text)
        self.assertIn("dispute_cases.status != 'cancelled'", text)


class FakeMonitorSession:
    """Risponde alle query del monitor in base al modello interrogato."""

    def __init__(self, now):
        self.now = now
        self.case = SimpleNamespace(
            id=uuid4(), location_id=1, case_code="DSP-TEST", unrecovered_amount=Decimal("10"),
            updated_at=now,  # modificata oggi (es. un allegato): non deve azzerare il timer
            status="credit_note_expected", due_date=None,
        )
        self.reconciliation = SimpleNamespace(
            id=uuid4(), status="awaiting_invoice", supplier_id=1, fattura_id=None,
            liquidstock_supplier_order_id=uuid4(),
            created_at=now - timedelta(days=12), updated_at=now - timedelta(days=10),
        )
        self.count_sql = []

    @staticmethod
    def entity(statement):
        return statement.column_descriptions[0]["entity"]

    async def scalars(self, statement):
        entity = self.entity(statement)
        rows = []
        if entity is DisputeCase and "dispute_cases.unrecovered_amount >" in sql(statement):
            rows = [self.case]
        elif entity in (LocationReconciliationSettings, DisputeCase, LiquidStockIntegrationEvent):
            rows = []
        return SimpleNamespace(all=lambda: rows)

    async def execute(self, statement, *args, **kwargs):
        entity = self.entity(statement)
        if entity is PurchaseOrderReconciliation:
            rows = [(self.reconciliation, SimpleNamespace(location_id=1))]
        elif entity is PurchaseOrderReconciliationAnomaly:
            rows = []
        elif entity is Anomalia:
            big = SimpleNamespace(id=7, delta_totale=Decimal("60.00"), stato_validazione=StatoValidazione.da_verificare)
            # 23,40 EUR: l'anomalia piu' alta oggi in produzione, sotto la soglia di 50.
            small = SimpleNamespace(id=8, delta_totale=Decimal("23.40"), stato_validazione=StatoValidazione.da_verificare)
            rows = [(big, 1), (small, 1)]
            self.anomaly_sql = sql(statement)
        else:
            self.audit_sql = sql(statement)
            rows = [(self.case.id, self.now - timedelta(days=10))]
        return FakeResult(rows=rows)

    async def scalar(self, statement):
        self.count_sql.append(sql(statement))
        return 2


class MonitorTest(unittest.TestCase):
    """B13: monitor operativo."""

    def detect(self):
        now = datetime.now(timezone.utc)
        db = FakeMonitorSession(now)
        with patch.object(automation, "_now", return_value=now):
            found = asyncio.run(automation._detect_alerts(db))
        return db, {alert.dedupe_key: alert for alert in found}

    def test_invoice_price_anomalies_raise_important_alert_above_threshold(self):
        db, alerts = self.detect()
        self.assertIn("important_anomaly:fattura:7", alerts)
        self.assertNotIn("important_anomaly:fattura:8", alerts)
        self.assertIn("skus_esclusi", db.anomaly_sql)
        self.assertIn("anomalie.stato_validazione IN ('da_verificare', 'contestata')", db.anomaly_sql)

    def test_credit_notes_are_not_invoice_candidates(self):
        db, alerts = self.detect()
        self.assertIn("fatture.tipo_documento NOT IN ('TD04', 'TD08')", db.count_sql[0])
        self.assertIn(f"invoice_candidate_available:{db.reconciliation.id}", alerts)

    def test_missing_credit_note_timer_uses_economic_events(self):
        db, alerts = self.detect()
        self.assertIn(f"credit_note_missing:{db.case.id}", alerts)
        self.assertIn("dispute_audit_events.action IN ('case_status_changed', 'recognition_recorded', 'credit_note_recorded')", db.audit_sql)

    def test_stalled_message_uses_configured_days(self):
        db, alerts = self.detect()
        message = alerts[f"reconciliation_stalled:{db.reconciliation.id}"].message
        self.assertIn("da oltre 3 giorni", message)
        self.assertNotIn("tre giorni", message)


if __name__ == "__main__":
    unittest.main()
