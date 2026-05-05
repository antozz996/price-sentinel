"""
Price Sentinel — Schemas Fatture, XMLRaw, RigheFattura.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ── XMLRaw ───────────────────────────────────

class XMLRawResponse(BaseModel):
    id: int
    nome_file: str | None
    hash_idempotenza: str
    stato_ingestion: str
    data_ricezione: datetime
    errore_dettaglio: str | None

    model_config = {"from_attributes": True}


# ── Fatture ──────────────────────────────────

class FatturaResponse(BaseModel):
    id: int
    xml_raw_id: int
    fornitore_id: int
    location_id: int
    numero_documento: str
    data_documento: date
    data_ricezione_sdi: date
    tipo_documento: str
    totale_imponibile: Decimal
    marker: str = "nessuno"

    model_config = {"from_attributes": True}


class FatturaListResponse(BaseModel):
    """Fattura con info correlate per lista."""
    id: int
    numero_documento: str
    data_documento: date
    tipo_documento: str
    totale_imponibile: Decimal
    fornitore_nome: str | None = None
    location_nome: str | None = None
    n_righe: int = 0
    n_anomalie: int = 0

    model_config = {"from_attributes": True}


# ── RigheFattura ─────────────────────────────

class RigaFatturaResponse(BaseModel):
    id: int
    fattura_id: int
    numero_linea: int
    codice_fornitore_raw: str | None
    descrizione_fornitore_raw: str | None
    sku_interno: str | None
    prezzo_unitario_fatturato: Decimal
    sconto_percentuale: Decimal
    prezzo_netto_normalizzato: Decimal
    quantita: Decimal
    unita_misura_fattura: str | None
    aliquota_iva: Decimal | None
    is_omaggio: bool
    stato_matching: str

    model_config = {"from_attributes": True}


# ── Webhook Aruba ────────────────────────────

class WebhookArubaPayload(BaseModel):
    """Payload inviato da Aruba via webhook."""
    xml_base64: str = Field(..., description="XML FatturaPA codificato in Base64")
    nome_file: str | None = Field(None, description="Nome file originale")
