"""
Price Sentinel — Schemas Location.
"""

from pydantic import BaseModel, Field


class LocationBase(BaseModel):
    nome_struttura: str = Field(..., max_length=255)
    piva_riferimento: str = Field(..., min_length=11, max_length=11)
    tipologia: str  # "balneare" | "ristorante" | "discoteca" | "evento"


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    nome_struttura: str | None = None
    tipologia: str | None = None


class LocationResponse(LocationBase):
    id: int

    model_config = {"from_attributes": True}
