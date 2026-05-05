"""
Price Sentinel — Schemas AliasProdotti.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AliasBase(BaseModel):
    fornitore_id: int
    codice_fornitore_originale: str = Field(..., max_length=100)
    sku_interno: str = Field(..., max_length=100)


class AliasCreate(AliasBase):
    pass


class AliasResponse(AliasBase):
    id: int
    confermato_da_user_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
