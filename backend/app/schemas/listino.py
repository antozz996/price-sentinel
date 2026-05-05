"""
Price Sentinel — Schemas Listino, PFA, UoM.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


# ── ListinoMaster ────────────────────────────

class ListinoBase(BaseModel):
    fornitore_id: int
    sku_interno: str = Field(..., max_length=100)
    descrizione: str
    prezzo_pattuito: Decimal = Field(..., decimal_places=4)
    unita_misura: str = Field(..., max_length=20)
    data_inizio_validita: date
    data_scadenza: date | None = None
    pfa_tipo: str | None = None  # "percentuale" | "fisso" | "scaglioni"
    pfa_valore: Decimal | None = None


class ListinoCreate(ListinoBase):
    pass


class ListinoUpdate(BaseModel):
    """Aggiornamento listino — crea nuova versione (append-only)."""
    prezzo_pattuito: Decimal | None = None
    data_inizio_validita: date | None = None
    pfa_tipo: str | None = None
    pfa_valore: Decimal | None = None


class ListinoResponse(ListinoBase):
    id: int

    model_config = {"from_attributes": True}


# ── PFA Scaglioni ────────────────────────────

class PFAScaglioneBase(BaseModel):
    listino_id: int
    soglia_da: Decimal
    soglia_a: Decimal | None = None
    valore_percentuale: Decimal


class PFAScaglioneCreate(PFAScaglioneBase):
    pass


class PFAScaglioneResponse(PFAScaglioneBase):
    id: int

    model_config = {"from_attributes": True}


# ── UoM Conversioni ─────────────────────────

class UoMConversioneBase(BaseModel):
    listino_id: int
    uom_fattura: str = Field(..., max_length=20)
    coefficiente: Decimal


class UoMConversioneCreate(UoMConversioneBase):
    pass


class UoMConversioneResponse(UoMConversioneBase):
    id: int

    model_config = {"from_attributes": True}
