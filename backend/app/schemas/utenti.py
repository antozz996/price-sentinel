"""
Price Sentinel — Schemas Utenti.
"""

from pydantic import BaseModel, EmailStr


class UtenteBase(BaseModel):
    email: EmailStr
    ruolo: str  # "admin" | "manager"
    nome_completo: str | None = None
    ruolo_dettagliato: str | None = "admin"
    settore_abilitato: str | None = "all"
    location_id: int | None = None
    attivo: bool = True


class UtenteCreate(UtenteBase):
    password: str


class UtenteUpdate(BaseModel):
    email: EmailStr | None = None
    nome_completo: str | None = None
    ruolo: str | None = None
    ruolo_dettagliato: str | None = None
    settore_abilitato: str | None = None
    location_id: int | None = None
    attivo: bool | None = None
    password: str | None = None


class UtenteResponse(UtenteBase):
    id: int

    model_config = {"from_attributes": True}


class UtenteLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    ruolo: str
    ruolo_dettagliato: str | None = None
    settore_abilitato: str | None = None
    nome_completo: str | None = None
    location_id: int | None = None
