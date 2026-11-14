"""Integrità dell'importazione: un XML produce una sola fattura.

Nessun database: la sessione è finta e riproduce solo il lock FOR UPDATE e la
tabella fatture, quanto basta per provare idempotenza e concorrenza.
"""
import asyncio
import importlib.util
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy.dialects import postgresql  # noqa: E402

from app import schema_guards  # noqa: E402
from app.models.fatture import Fattura, TipoDocumento  # noqa: E402
from app.services import ingestion  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


class FakeDatabase:
    """Stato condiviso tra sessioni: fatture per xml_raw e lock di riga."""

    def __init__(self, existing=None):
        self.fatture: dict[int, list[int]] = dict(existing or {})
        self.row_locks: dict[int, asyncio.Lock] = {}
        self.next_id = 1000


class FakeSession:
    def __init__(self, database: FakeDatabase):
        self.database = database
        self.held: list[asyncio.Lock] = []
        self.statements: list[str] = []

    async def execute(self, statement, *args, **kwargs):
        text = sql(statement)
        self.statements.append(text)
        if "FOR UPDATE" in text and "xml_raw" in text:
            xml_raw_id = statement.compile().params["id_1"]
            lock = self.database.row_locks.setdefault(xml_raw_id, asyncio.Lock())
            await lock.acquire()  # la seconda sessione aspetta qui
            self.held.append(lock)
        return MagicMock()

    async def scalar(self, statement, *args, **kwargs):
        text = sql(statement)
        self.statements.append(text)
        xml_raw_id = statement.compile().params["xml_raw_id_1"]
        ids = self.database.fatture.get(xml_raw_id, [])
        return min(ids) if ids else None

    def commit(self):
        for lock in self.held:
            lock.release()
        self.held.clear()


def parsed_td01():
    return SimpleNamespace(
        tipo_documento="TD01", piva_cedente="IT01", piva_cessionario="IT02",
        righe=[object()], is_valid=True, errori=[],
    )


async def fake_td01(db, xml_raw_id, parsed, fornitore, location):
    # Simula il lavoro (matching, flush) con un punto di sospensione in mezzo.
    await asyncio.sleep(0)
    db.database.next_id += 1
    db.database.fatture.setdefault(xml_raw_id, []).append(db.database.next_id)
    return {"status": "success", "fattura_id": db.database.next_id}


async def run_pipeline(session, xml_raw_id=7):
    try:
        return await ingestion.process_xml_raw(session, xml_raw_id, parsed_td01())
    finally:
        session.commit()


def pipeline_patches():
    fornitore = SimpleNamespace(id=1, attivo_whitelist=True)
    return (
        patch.object(ingestion, "_resolve_fornitore", AsyncMock(return_value=fornitore)),
        patch.object(ingestion, "_resolve_location", AsyncMock(return_value=SimpleNamespace(id=2))),
        patch.object(ingestion, "_set_xml_stato", AsyncMock()),
        patch.object(ingestion, "_process_td01", side_effect=fake_td01),
    )


class ProcessXmlRawIdempotenceTest(unittest.TestCase):
    def run_with_patches(self, coro_factory):
        patches = pipeline_patches()
        for p in patches:
            p.start()
        try:
            return asyncio.run(coro_factory())
        finally:
            for p in reversed(patches):
                p.stop()

    def test_same_xml_twice_creates_one_invoice(self):
        database = FakeDatabase()

        async def scenario():
            first = await run_pipeline(FakeSession(database))
            second = await run_pipeline(FakeSession(database))
            return first, second

        first, second = self.run_with_patches(scenario)
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], ingestion.STATUS_GIA_PRESENTE)
        self.assertEqual(second["fattura_id"], first["fattura_id"])
        self.assertEqual(len(database.fatture[7]), 1)

    def test_two_parallel_runs_give_one_invoice_and_one_gia_presente(self):
        database = FakeDatabase()

        async def scenario():
            return await asyncio.gather(
                run_pipeline(FakeSession(database)), run_pipeline(FakeSession(database))
            )

        reports = self.run_with_patches(scenario)
        statuses = sorted(r["status"] for r in reports)
        self.assertEqual(statuses, sorted(["success", ingestion.STATUS_GIA_PRESENTE]))
        self.assertEqual(len(database.fatture[7]), 1)

    def test_existing_invoice_stops_before_any_write(self):
        database = FakeDatabase(existing={7: [42, 99]})  # anche con doppioni storici
        session = FakeSession(database)

        report = self.run_with_patches(lambda: run_pipeline(session))
        self.assertEqual(report["status"], ingestion.STATUS_GIA_PRESENTE)
        self.assertEqual(report["fattura_id"], 42)
        self.assertEqual(database.fatture[7], [42, 99])  # nessuna nuova fattura

    def test_lock_statement_is_select_for_update_on_xml_raw(self):
        session = FakeSession(FakeDatabase())
        asyncio.run(ingestion.lock_xml_raw_and_find_fattura(session, 7))
        session.commit()
        self.assertIn("FOR UPDATE", session.statements[0])
        self.assertIn("FROM xml_raw", session.statements[0])
        self.assertIn("FROM fatture", session.statements[1])


class UniqueIndexTest(unittest.TestCase):
    def test_model_declares_unique_index_on_xml_raw_id(self):
        indexes = {index.name: index for index in Fattura.__table__.indexes}
        index = indexes[schema_guards.FATTURE_XML_RAW_UNIQUE_INDEX]
        self.assertTrue(index.unique)
        self.assertEqual([c.name for c in index.columns], ["xml_raw_id"])

    def test_startup_guard_skips_index_while_duplicates_exist(self):
        conn = MagicMock()
        conn.scalar = AsyncMock(return_value=39)
        conn.execute = AsyncMock()
        with self.assertLogs("price_sentinel.schema", level="WARNING") as logs:
            created = asyncio.run(schema_guards.ensure_unique_invoice_per_xml(conn))
        self.assertFalse(created)
        conn.execute.assert_not_awaited()
        self.assertIn("39", logs.output[0])

    def test_startup_guard_creates_index_when_clean(self):
        conn = MagicMock()
        conn.scalar = AsyncMock(return_value=0)
        conn.execute = AsyncMock()
        created = asyncio.run(schema_guards.ensure_unique_invoice_per_xml(conn))
        self.assertTrue(created)
        statement = str(conn.execute.await_args.args[0])
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS uq_fatture_xml_raw_id", statement)

    def load_migration(self):
        path = BACKEND / "alembic" / "versions" / "2026_11_14_fatture_xml_raw_unico.py"
        spec = importlib.util.spec_from_file_location("fatture_xml_raw_unico", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migration_fails_clearly_with_duplicates(self):
        migration = self.load_migration()
        bind = MagicMock()
        bind.execute.return_value.scalar.return_value = 39
        with patch.object(migration, "op") as op:
            op.get_bind.return_value = bind
            with self.assertRaisesRegex(RuntimeError, "39 xml_raw"):
                migration.upgrade()
            op.execute.assert_not_called()

    def test_migration_creates_index_when_clean(self):
        migration = self.load_migration()
        bind = MagicMock()
        bind.execute.return_value.scalar.return_value = 0
        with patch.object(migration, "op") as op:
            op.get_bind.return_value = bind
            migration.upgrade()
            self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS", op.execute.call_args.args[0])
        self.assertEqual(migration.down_revision, "alias_fattore_confezione")

    def test_ci_expects_new_alembic_head(self):
        script = (BACKEND / "scripts" / "run_ci_disposable_e2e.py").read_text(encoding="utf-8")
        self.assertIn('("fatture_xml_raw_unico",)', script)


class InvoicedNetPriceIsNeverRewrittenTest(unittest.TestCase):
    """Il prezzo convertito vive solo nello snapshot dell'anomalia (PR #140)."""

    def test_no_code_assigns_prezzo_netto_normalizzato_on_an_existing_line(self):
        offenders = []
        pattern = re.compile(r"\.prezzo_netto_normalizzato\s*=(?!=)|SET\s+prezzo_netto_normalizzato", re.I)
        for path in (BACKEND / "app").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(BACKEND)}:{number}")
        self.assertEqual(offenders, [])


class Td08CommentTest(unittest.TestCase):
    def test_td08_is_documented_as_credit_note(self):
        source = (BACKEND / "app" / "models" / "fatture.py").read_text(encoding="utf-8")
        line = next(l for l in source.splitlines() if 'TD08 = "TD08"' in l)
        self.assertIn("Nota di Credito", line)
        self.assertEqual(TipoDocumento.TD08.value, "TD08")


if __name__ == "__main__":
    unittest.main()
