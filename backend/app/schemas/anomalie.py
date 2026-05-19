"""
Price Sentinel — Schemas Anomalie e Note di Credito.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ── Anomalie ─────────────────────────────────

class AnomaliaResponse(BaseModel):
    id: int
    riga_fattura_id: int
    delta_prezzo: Decimal
    delta_totale: Decimal
    prezzo_listino_snapshot: Decimal
    prezzo_fatturato_snapshot: Decimal
    stato_validazione: str
    nota_manager: str | None
    validato_da_user_id: int | None
    validato_at: datetime | None
    gestito_da_admin_id: int | None
    gestito_at: datetime | None
    
    # Campi calcolati relazionali
    descrizione_orig: str | None = None
    fornitore_nome: str | None = None
    quantita: Decimal | None = None
    codice_fornitore: str | None = None

    model_config = {"from_attributes": True}


class AnomaliaAzione(BaseModel):
    """Azione di un Manager sulla riga anomala — Spec §4.2."""
    azione: str = Field(
        ...,
        description="segnala | accetta | proponi_aggiornamento | parcheggia",
    )
    nota: str | None = Field(
        None,
        description="Obbligatoria se azione=accetta",
    )


class AnomaliaEscalation(BaseModel):
    """Azione Admin su anomalia contestata — Spec §4.3."""
    azione: str = Field(
        ...,
        description="reclamo | registra_nc",
    )


# ── Note di Credito ──────────────────────────

class NotaDiCreditoCreate(BaseModel):
    anomalia_id: int
    importo_recuperato: Decimal
    data_emissione_nc: date
    numero_nc: str | None = None


class NotaDiCreditoResponse(BaseModel):
    id: int
    anomalia_id: int
    importo_recuperato: Decimal
    data_emissione_nc: date
    data_registrazione: date
    numero_nc: str | None
    registrato_da_admin_id: int

    model_config = {"from_attributes": True}
