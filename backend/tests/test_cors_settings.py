"""CORS configuration tests; no database or network access required."""
from __future__ import annotations

import unittest

from app.cors import parse_cors_allowed_origins


class CorsSettingsTests(unittest.TestCase):
    def test_empty_means_same_origin_only(self) -> None:
        self.assertEqual(parse_cors_allowed_origins(""), [])

    def test_normalizes_and_deduplicates_exact_origins(self) -> None:
        configured = parse_cors_allowed_origins(
            " https://price-sentinel-omega.vercel.app/,"
            "https://price-sentinel-omega.vercel.app,"
            "http://localhost:5173 "
        )
        self.assertEqual(
            configured,
            [
                "https://price-sentinel-omega.vercel.app",
                "http://localhost:5173",
            ],
        )

    def test_rejects_wildcards_and_paths(self) -> None:
        for origin in ("https://*.vercel.app", "https://example.com/path"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                parse_cors_allowed_origins(origin)


if __name__ == "__main__":
    unittest.main()
