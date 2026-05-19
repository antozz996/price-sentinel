from datetime import datetime
from pydantic import BaseModel, Field

class ApprovazionePrezzoBase(BaseModel):
    sku_interno: str = Field(..., description="SKU interno del prodotto")
    descrizione_orig: str = Field(..., description="Descrizione originale in fattura")
    mese: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="Mese di riferimento in formato YYYY-MM")
    prezzo_approvato: float = Field(..., description="Prezzo unitario approvato manualmente")
    stato: str = Field("APPROVATO", description="Stato dell'approvazione")

class ApprovazionePrezzoCreate(ApprovazionePrezzoBase):
    pass

class ApprovazionePrezzoResponse(ApprovazionePrezzoBase):
    created_at: datetime

    class Config:
        from_attributes = True
