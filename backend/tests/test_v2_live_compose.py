"""Offline guard for the V2 live Compose promotion override."""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class V2LiveComposeTests(unittest.TestCase):
    def test_live_override_is_production_with_internal_monitor(self) -> None:
        document = yaml.safe_load((ROOT / "docker-compose.v2-live.yml").read_text())
        backend = document["services"]["backend"]
        environment = backend["environment"]
        command = " ".join(backend["command"])

        self.assertEqual(environment["ENVIRONMENT"], "production")
        self.assertEqual(environment["DEBUG"], "false")
        self.assertEqual(environment["AUTOMATION_ENABLED"], "true")
        self.assertIn("uvicorn app.main:app", command)
        self.assertNotIn("ensure_v2_staging", command)
        self.assertNotIn("alembic upgrade", command)


if __name__ == "__main__":
    unittest.main()
