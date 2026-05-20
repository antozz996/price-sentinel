"""
Price Sentinel — Dependency Injection.
Autenticazione JWT, controllo ruoli, validazione API Key Aruba.
"""

from fastapi import Depends, Header, HTTPException, status, Query
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.utenti import Utente


# ─────────────────────────────────────────────
# Auth Dependencies
# ─────────────────────────────────────────────

async def get_current_user(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Utente:
    """
    Decodifica il JWT dal header Authorization: Bearer <token>.
    Restituisce l'utente attivo corrispondente.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Estrai token dal header "Bearer xxx"
    if not authorization.startswith("Bearer "):
        raise credentials_exception

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Cerca l'utente nel DB
    result = await db.execute(select(Utente).where(Utente.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.attivo:
        raise credentials_exception

    return user


async def get_current_user_from_query(
    token: str = Query(..., description="JWT token passato come query parameter"),
    db: AsyncSession = Depends(get_db),
) -> Utente:
    """
    Decodifica il JWT dal query parameter token.
    Restituisce l'utente attivo corrispondente.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Cerca l'utente nel DB
    result = await db.execute(select(Utente).where(Utente.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.attivo:
        raise credentials_exception

    return user


async def require_admin(
    current_user: Utente = Depends(get_current_user),
) -> Utente:
    """Verifica che l'utente corrente sia Admin."""
    if current_user.ruolo.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato agli amministratori",
        )
    return current_user


async def require_manager(
    current_user: Utente = Depends(get_current_user),
) -> Utente:
    """Verifica che l'utente corrente sia Manager o Admin."""
    if current_user.ruolo.value not in ["manager", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato ai manager o amministratori",
        )
    return current_user


# ─────────────────────────────────────────────
# Webhook API Key Validation
# ─────────────────────────────────────────────

async def verify_aruba_api_key(
    authorization: str = Header(..., alias="Authorization"),
) -> None:
    """
    Valida l'API Key statica del webhook Aruba.
    Spec §1.2: Richieste prive di chiave valida vengono rifiutate
    con HTTP 401 PRIMA di qualsiasi elaborazione.
    """
    expected = f"ApiKey {settings.ARUBA_WEBHOOK_API_KEY}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key non valida",
        )
