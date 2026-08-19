"""
Price Sentinel — Auth Router.
Login e generazione JWT token.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.utenti import Utente
from app.schemas.utenti import TokenResponse, UtenteLogin, UtenteResponse
from app.services.auth import create_access_token, verify_password

router = APIRouter()


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

    token = create_access_token(
        user_id=user.id,
        ruolo=user.ruolo.value,
        location_id=user.location_id,
        tenant_id=user.tenant_id or 1,
    )

    return TokenResponse(
        access_token=token,
        ruolo=user.ruolo.value,
        ruolo_dettagliato=user.ruolo_dettagliato or user.ruolo.value,
        settore_abilitato=user.settore_abilitato or "all",
        nome_completo=user.nome_completo,
        location_id=user.location_id,
        tenant_id=user.tenant_id or 1,
    )


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
    summary="Refresh del token JWT",
    description="Genera un nuovo token JWT a partire dal token esistente (se valido e l'utente è attivo).",
)
async def refresh_token(
    current_user: Utente = Depends(get_current_user),
) -> TokenResponse:
    """Rigenera il JWT per l'utente corrente."""
    token = create_access_token(
        user_id=current_user.id,
        ruolo=current_user.ruolo.value,
        location_id=current_user.location_id,
    )
    return TokenResponse(
        access_token=token,
        ruolo=current_user.ruolo.value,
        ruolo_dettagliato=current_user.ruolo_dettagliato or current_user.ruolo.value,
        settore_abilitato=current_user.settore_abilitato or "all",
        nome_completo=current_user.nome_completo,
        location_id=current_user.location_id,
    )
