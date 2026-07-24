"""Focused tests for HMAC verification and key rotation."""

import json
import os
import time
from uuid import uuid4

from fastapi import HTTPException
from starlette.requests import Request

from app.services.liquidstock_auth import (
    signature_for,
    verify_liquidstock_request,
)


CURRENT = os.environ["LIQUIDSTOCK_INTEGRATION_SECRET"]
PREVIOUS = os.environ["LIQUIDSTOCK_INTEGRATION_PREVIOUS_SECRET"]
NOW = int(time.time())
RAW = json.dumps({"integration_version": "1.0"}, separators=(",", ":")).encode()
EVENT_ID = str(uuid4())
results: list[str] = []


def request(secret: str, *, host: str = "localhost", proto: str = "http"):
    signature = signature_for(secret, NOW, RAW)
    headers = [
        (b"host", host.encode()),
        (b"x-integration-source", b"liquidstock"),
        (b"x-event-id", EVENT_ID.encode()),
        (b"x-event-timestamp", str(NOW).encode()),
        (b"x-event-signature", signature.encode()),
    ]
    if proto:
        headers.append((b"x-forwarded-proto", proto.encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "server": (host, 80),
        "path": "/",
        "query_string": b"",
        "headers": headers,
    })


def check(name: str, condition: bool):
    if not condition:
        raise AssertionError(name)
    results.append(name)


check(
    "current secret accepted",
    str(verify_liquidstock_request(request(CURRENT), RAW, now=NOW).event_id)
    == EVENT_ID,
)
check(
    "previous rotation secret accepted",
    str(verify_liquidstock_request(request(PREVIOUS), RAW, now=NOW).event_id)
    == EVENT_ID,
)
try:
    verify_liquidstock_request(request("wrong-secret"), RAW, now=NOW)
    check("wrong secret rejected", False)
except HTTPException as error:
    check("wrong secret rejected", error.status_code == 401)
try:
    verify_liquidstock_request(
        request(CURRENT, host="integration.example.test", proto="http"),
        RAW,
        now=NOW,
    )
    check("HTTP outside local rejected", False)
except HTTPException as error:
    check("HTTP outside local rejected", error.status_code == 400)
check(
    "HTTPS outside local accepted",
    str(
        verify_liquidstock_request(
            request(CURRENT, host="integration.example.test", proto="https"),
            RAW,
            now=NOW,
        ).event_id
    )
    == EVENT_ID,
)

print(json.dumps({"status": "PASS", "tests": len(results), "results": results}, indent=2))
