"""
Price Sentinel — Schemas Utenti.
"""

from pydantic import BaseModel, EmailStr


class UtenteBase(BaseModel):
    email: EmailStr
    ruolo: str  # "admin" | "manager"
    location_id: int | None = None
    attivo: bool = True


class UtenteCreate(UtenteBase):
    password: str


class UtenteUpdate(BaseModel):
    email: EmailStr | None = None
    ruolo: str | None = None
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
    location_id: int | None = None
