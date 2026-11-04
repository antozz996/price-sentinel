"""
Price Sentinel — Auth Service.
JWT token generation + bcrypt password hashing.
"""

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

# ── Password Hashing ────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash una password con bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica password plaintext contro hash bcrypt."""
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Tokens ───────────────────────────────

REFRESH_TOKEN_TYPE = "refresh"
# Vale per le nuove password: quelle esistenti continuano a funzionare.
MIN_PASSWORD_LENGTH = 12


def create_access_token(
    user_id: int,
    ruolo: str,
    location_id: int | None = None,
    tenant_id: int | None = 1,
    expires_delta: timedelta | None = None,
    session_version: int | None = None,
) -> str:
    """
    Genera un JWT con payload:
    - sub: user_id
    - ruolo: admin|manager
    - location_id: per filtraggio dati (solo manager)
    - tenant_id: isolamento multi-tenant azienda
    - exp: scadenza
    - rv: versione di sessione, se il token va revocato al logout
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ruolo": ruolo,
        "location_id": location_id,
        "tenant_id": tenant_id or 1,
        "iat": now,
        "exp": now + expires_delta,
    }
    if session_version is not None:
        payload["rv"] = session_version
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: int, session_version: int) -> str:
    """Genera il token di rinnovo: scade dopo 7 giorni senza attività."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": REFRESH_TOKEN_TYPE,
        "rv": session_version,
        "iat": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def is_token_valid_for_session(claims: dict, current_version: int) -> bool:
    """Un token senza versione precede questa funzione e scade da solo entro 30 minuti."""
    version = claims.get("rv")
    return version is None or version == current_version


def decode_access_token(token: str) -> dict:
    """Decodifica un JWT. Solleva JWTError se non valido/scaduto."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
