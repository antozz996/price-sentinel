"""
Price Sentinel — Schemas Fornitori.
"""

from pydantic import BaseModel, EmailStr, Field


class FornitoreBase(BaseModel):
    partita_iva: str = Field(..., min_length=2, max_length=20)
    nome_azienda: str = Field(..., max_length=255)
    attivo_whitelist: bool = True
    email_contatto: EmailStr | None = None


class FornitoreCreate(FornitoreBase):
    pass


class FornitoreUpdate(BaseModel):
    nome_azienda: str | None = None
    attivo_whitelist: bool | None = None
    email_contatto: EmailStr | None = None


class FornitoreResponse(FornitoreBase):
    id: int

    model_config = {"from_attributes": True}
