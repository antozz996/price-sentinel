"""
Price Sentinel — Schemas Utenti.
"""

from pydantic import BaseModel, EmailStr, field_validator

from app.password_policy import MIN_PASSWORD_LENGTH


def _require_strong_password(value: str | None) -> str | None:
    # An empty password in an update means "leave it unchanged".
    if value and len(value.strip()) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La password deve contenere almeno {MIN_PASSWORD_LENGTH} caratteri")
    return value


class UtenteBase(BaseModel):
    email: EmailStr
    ruolo: str  # "admin" | "manager"
    nome_completo: str | None = None
    ruolo_dettagliato: str | None = "admin"
    settore_abilitato: str | None = "all"
    location_id: int | None = None
    tenant_id: int | None = 1
    attivo: bool = True


class UtenteCreate(UtenteBase):
    password: str

    _strong_password = field_validator("password")(_require_strong_password)


class UtenteUpdate(BaseModel):
    email: EmailStr | None = None
    nome_completo: str | None = None
    ruolo: str | None = None
    ruolo_dettagliato: str | None = None
    settore_abilitato: str | None = None
    location_id: int | None = None
    tenant_id: int | None = None
    attivo: bool | None = None
    password: str | None = None

    _strong_password = field_validator("password")(_require_strong_password)


class UtenteResponse(UtenteBase):
    id: int

    model_config = {"from_attributes": True}


class UtenteLogin(BaseModel):
    email: EmailStr
    password: str


class SessionTokenRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    ruolo: str
    ruolo_dettagliato: str | None = None
    settore_abilitato: str | None = None
    nome_completo: str | None = None
    location_id: int | None = None
    tenant_id: int | None = 1
