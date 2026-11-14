"""refresh_line_anomaly: a re-link or an approval never removes an anomaly someone is working on."""
import asyncio
import os
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services import anomaly_policy  # noqa: E402


def run(db, delta_unit="0.50", delta_total="1.00", in_scope=True):
    archive = AsyncMock(return_value=0)
    with patch.object(anomaly_policy, "archive_and_remove_anomalies", archive), \
            patch.object(anomaly_policy, "invoice_in_check_scope", AsyncMock(return_value=in_scope)):
        added = asyncio.run(anomaly_policy.refresh_line_anomaly(
            db, riga_fattura_id=7, xml_raw_id=1, listino_price=Decimal("2.00"), compared_price=Decimal("2.50"),
            delta_unit=Decimal(delta_unit), delta_total=Decimal(delta_total), reason="prova"))
    return added, archive


def fake_db(remaining_id=None):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=remaining_id)
    return db


class RefreshLineAnomalyTest(unittest.TestCase):
    def test_only_unworked_anomalies_are_archived(self):
        db = fake_db()
        _added, archive = run(db)
        archive.assert_awaited_once()
        args, kwargs = archive.call_args
        self.assertEqual(kwargs["reason"], "prova")  # replaced by a new anomaly
        # Same conditions as stale_unworked_anomaly_conditions: never a bare "riga_fattura_id == x".
        expected = [str(c) for c in anomaly_policy.stale_unworked_anomaly_conditions(7)]
        self.assertEqual([str(c) for c in args[1:]], expected)

    def test_new_anomaly_when_material_and_nothing_left(self):
        db = fake_db(None)
        added, _ = run(db)
        self.assertTrue(added)
        db.add.assert_called_once()
        anomaly = db.add.call_args.args[0]
        self.assertEqual(anomaly.riga_fattura_id, 7)
        self.assertEqual(anomaly.delta_totale, Decimal("1.00"))
        self.assertEqual(anomaly.prezzo_fatturato_snapshot, Decimal("2.50"))

    def test_worked_anomaly_blocks_a_new_one(self):
        db = fake_db(remaining_id=42)
        added, _ = run(db)
        self.assertFalse(added)
        db.add.assert_not_called()

    def test_below_threshold_only_archives(self):
        db = fake_db(None)
        added, archive = run(db, delta_unit="0.10", delta_total="0.10")
        self.assertFalse(added)
        archive.assert_awaited_once()
        self.assertEqual(archive.call_args.kwargs["reason"], "riassociazione_sotto_soglia")
        db.add.assert_not_called()

    def test_invoice_outside_check_scope(self):
        db = fake_db(None)
        added, _ = run(db, in_scope=False)
        self.assertFalse(added)
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
