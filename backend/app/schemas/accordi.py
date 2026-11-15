from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field

class PFAScaglioneInfo(BaseModel):
    id: int
    listino_id: int
    soglia_da: Decimal = Field(..., decimal_places=2)
    soglia_a: Decimal | None = Field(None, decimal_places=2)
    valore_percentuale: Decimal = Field(..., decimal_places=4)

    model_config = {"from_attributes": True}

class AccordoCommercialeResponse(BaseModel):
    listino_id: int
    sku_interno: str
    descrizione: str
    fornitore_id: int
    fornitore_nome: str
    unita_misura: str | None = None
    prezzo_pattuito: Decimal = Field(..., decimal_places=4)
    pfa_tipo: str | None = None
    pfa_valore: Decimal | None = Field(None, decimal_places=4)
    pfa_scaglioni: list[PFAScaglioneInfo] = []
    
    # Calculated statistics
    netto_rientro_contratto: Decimal | None = Field(None, decimal_places=4)
    # None quando le righe sono in unita non convertibili nell'unita dell'accordo
    # (unita_non_omogenee): meglio nessun numero che cartoni sommati a pezzi.
    quantita_acquistata: Decimal | None = Field(None, decimal_places=4)
    totale_fatturato: Decimal = Field(..., decimal_places=4)
    rientro_accumulato: Decimal | None = Field(None, decimal_places=4)
    netto_rientro_medio: Decimal | None = Field(None, decimal_places=4)
    unita_non_omogenee: bool = False
    righe_non_convertibili: int = 0
    # Periodo usato per quantita e fatturato (predefinito: anno solare in corso).
    periodo_da: date | None = None
    periodo_a: date | None = None

    model_config = {"from_attributes": True}
