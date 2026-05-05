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

def create_access_token(
    user_id: int,
    ruolo: str,
    location_id: int | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Genera un JWT con payload:
    - sub: user_id
    - ruolo: admin|manager
    - location_id: per filtraggio dati (solo manager)
    - exp: scadenza
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ruolo": ruolo,
        "location_id": location_id,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decodifica un JWT. Solleva JWTError se non valido/scaduto."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
