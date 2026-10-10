"""Offline V2 guard tests. No database or external services required."""
from __future__ import annotations

import unittest

from scripts.ensure_v2_staging import validate


def environment() -> dict[str, str]:
    return {
        "ENVIRONMENT": "staging",
        "DEBUG": "false",
        "AUTOMATION_ENABLED": "false",
        "DATABASE_URL": (
            "postgresql+asyncpg://ps_v2_app:"
            "random_staging_db_password_2026_ABC@db:5432/price_sentinel_v2_staging"
        ),
        "SECRET_KEY": "staging_private_jwt_test_secret_1234567890",
        "ARUBA_WEBHOOK_API_KEY": "independent_test_webhook_key",
        "LIQUIDSTOCK_INTEGRATION_SECRET": "independent_test_bridge_secret_that_is_disabled",
    }


class StagingIsolationTests(unittest.TestCase):
    def test_accept_dedicated_test_database(self) -> None:
        validate(environment())

    def test_reject_production_database_name(self) -> None:
        e = environment()
        e["DATABASE_URL"] = e["DATABASE_URL"].replace(
            "price_sentinel_v2_staging", "price_sentinel"
        )
        with self.assertRaisesRegex(ValueError, "isolated"):
            validate(e)

    def test_reject_remote_host(self) -> None:
        e = environment()
        e["DATABASE_URL"] = e["DATABASE_URL"].replace("@db:", "@production-db:")
        with self.assertRaisesRegex(ValueError, "isolated"):
            validate(e)

    def test_reject_production_database_username(self) -> None:
        e = environment()
        e["DATABASE_URL"] = e["DATABASE_URL"].replace("ps_v2_app:", "ps_app:")
        with self.assertRaisesRegex(ValueError, "isolated"):
            validate(e)

    def test_reject_automation_enabled(self) -> None:
        e = environment()
        e["AUTOMATION_ENABLED"] = "true"
        with self.assertRaisesRegex(ValueError, "automations"):
            validate(e)

    def test_reject_debug_enabled(self) -> None:
        e = environment()
        e["DEBUG"] = "true"
        with self.assertRaisesRegex(ValueError, "DEBUG"):
            validate(e)

    def test_reject_placeholder_secret(self) -> None:
        e = environment()
        e["SECRET_KEY"] = "REPLACE_WITH_STAGING_PRIVATE_JWT_SECRET_ABC"
        with self.assertRaisesRegex(ValueError, "non-placeholder"):
            validate(e)

    def test_reject_nonstaging_environment(self) -> None:
        e = environment()
        e["ENVIRONMENT"] = "production"
        with self.assertRaisesRegex(ValueError, "staging"):
            validate(e)


if __name__ == "__main__":
    unittest.main()
