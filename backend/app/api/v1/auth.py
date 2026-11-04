"""
Price Sentinel — Auth Router.
Login e generazione JWT token.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.utenti import Utente
from app.schemas.utenti import SessionTokenRequest, TokenResponse, UtenteLogin, UtenteResponse
from app.password_policy import MIN_PASSWORD_LENGTH
from app.services.auth import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    is_token_valid_for_session,
    verify_password,
)

router = APIRouter()


def _session_response(user: Utente, *, with_refresh_token: bool = True) -> TokenResponse:
    version = user.refresh_token_version
    return TokenResponse(
        access_token=create_access_token(
            user_id=user.id,
            ruolo=user.ruolo.value,
            location_id=user.location_id,
            tenant_id=user.tenant_id or 1,
            session_version=version,
        ),
        refresh_token=create_refresh_token(user.id, version) if with_refresh_token else None,
        ruolo=user.ruolo.value,
        ruolo_dettagliato=user.ruolo_dettagliato or user.ruolo.value,
        settore_abilitato=user.settore_abilitato or "all",
        nome_completo=user.nome_completo,
        location_id=user.location_id,
        tenant_id=user.tenant_id or 1,
    )


async def _user_from_refresh_token(token: str, db: AsyncSession) -> Utente:
    invalid_session = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessione scaduta",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
    except JWTError:
        raise invalid_session
    if claims.get("typ") != REFRESH_TOKEN_TYPE or claims.get("sub") is None:
        raise invalid_session

    user = await db.scalar(select(Utente).where(Utente.id == int(claims["sub"])))
    if user is None or not user.attivo or not is_token_valid_for_session(claims, user.refresh_token_version):
        raise invalid_session
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login utente",
    description="Autenticazione con email e password. Restituisce JWT token.",
)
async def login(
    data: UtenteLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Autentica l'utente e genera il JWT."""
    result = await db.execute(
        select(Utente).where(Utente.email == data.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o password non corretti",
        )

    if not user.attivo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disattivato",
        )

    return _session_response(user)


from app.api.deps import get_current_user


@router.get(
    "/me",
    response_model=UtenteResponse,
    summary="Profilo autenticato corrente",
)
async def current_profile(
    current_user: Utente = Depends(get_current_user),
) -> UtenteResponse:
    return current_user

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rinnovo della sessione",
    description="Con un token di rinnovo valido emette nuovi token e sposta la scadenza a 7 giorni. "
    "Senza token di rinnovo rinnova solo un JWT ancora valido: serve alle sessioni aperte prima di questa versione.",
)
async def refresh_token(
    data: SessionTokenRequest | None = None,
    authorization: str | None = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    if data and data.refresh_token:
        return _session_response(await _user_from_refresh_token(data.refresh_token, db))
    if authorization:
        return _session_response(await get_current_user(authorization, db), with_refresh_token=False)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessione scaduta")


@router.post("/logout", summary="Termina la sessione su tutti i dispositivi")
async def logout(
    data: SessionTokenRequest | None = None,
    authorization: str | None = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Una sessione già scaduta non ha nulla da revocare, quindi il logout riesce comunque."""
    user: Utente | None = None
    try:
        if data and data.refresh_token:
            user = await _user_from_refresh_token(data.refresh_token, db)
        elif authorization:
            user = await get_current_user(authorization, db)
    except HTTPException:
        user = None
    if user is not None:
        user.refresh_token_version += 1
        await db.commit()
    return {"status": "success"}


from pydantic import BaseModel


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


from app.services.auth import hash_password


@router.post(
    "/change-password",
    summary="Cambio password per l'utente autenticato",
    description="Consente a qualsiasi utente autenticato di cambiare la propria password fornendo la password attuale e la nuova password.",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La password attuale non è corretta",
        )

    if len(data.new_password.strip()) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La nuova password deve contenere almeno {MIN_PASSWORD_LENGTH} caratteri",
        )

    current_user.password_hash = hash_password(data.new_password.strip())
    # Chiude ogni altra sessione: questo dispositivo resta dentro con i nuovi token.
    current_user.refresh_token_version += 1
    session = _session_response(current_user)
    await db.commit()

    return {
        "status": "success",
        "message": "Password modificata con successo!",
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
    }

