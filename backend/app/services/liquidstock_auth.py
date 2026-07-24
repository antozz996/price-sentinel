"""HMAC authentication for the LiquidStock server-to-server channel."""

from dataclasses import dataclass
from hashlib import sha256
import hmac
import re
import time
from uuid import UUID

from fastapi import HTTPException, Request, status

from app.config import settings


SIGNATURE_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal", "testserver"}


@dataclass(frozen=True)
class VerifiedIntegrationRequest:
    event_id: UUID
    timestamp: int


def signature_for(secret: str, timestamp: int, raw_body: bytes) -> str:
    signed = str(timestamp).encode("ascii") + b"." + raw_body
    return hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()


def _request_is_https_or_local(request: Request) -> bool:
    hostname = (request.url.hostname or "").lower()
    if hostname in LOCAL_HOSTS:
        return True
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


def verify_liquidstock_request(
    request: Request,
    raw_body: bytes,
    *,
    now: int | None = None,
) -> VerifiedIntegrationRequest:
    if not _request_is_https_or_local(request):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="integration_request_rejected",
        )
    if request.headers.get("X-Integration-Source") != "liquidstock":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="integration_authentication_failed",
        )

    event_id_value = request.headers.get("X-Event-Id")
    timestamp_value = request.headers.get("X-Event-Timestamp")
    supplied_signature = request.headers.get("X-Event-Signature", "")
    try:
        event_id = UUID(event_id_value or "")
        timestamp = int(timestamp_value or "")
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="integration_authentication_failed",
        ) from None

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp) > settings.INTEGRATION_MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="integration_authentication_failed",
        )
    if not SIGNATURE_PATTERN.fullmatch(supplied_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="integration_authentication_failed",
        )

    secrets = [
        secret
        for secret in (
            settings.LIQUIDSTOCK_INTEGRATION_SECRET,
            settings.LIQUIDSTOCK_INTEGRATION_PREVIOUS_SECRET,
        )
        if secret
    ]
    if not secrets:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="integration_not_configured",
        )
    valid = False
    for secret in secrets:
        expected = signature_for(secret, timestamp, raw_body)
        valid = hmac.compare_digest(expected, supplied_signature.lower()) or valid
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="integration_authentication_failed",
        )
    return VerifiedIntegrationRequest(event_id=event_id, timestamp=timestamp)
