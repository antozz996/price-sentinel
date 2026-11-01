"""Strict parsing for browser origins allowed to call the API."""
from __future__ import annotations

from urllib.parse import urlsplit


def parse_cors_allowed_origins(value: str) -> list[str]:
    """Return exact, normalized HTTP(S) origins without wildcards."""
    origins: list[str] = []
    for raw_origin in value.split(","):
        origin = raw_origin.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must contain comma-separated exact "
                "HTTP(S) origins"
            )
        if origin not in origins:
            origins.append(origin)
    return origins
