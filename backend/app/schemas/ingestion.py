from datetime import datetime
from pydantic import BaseModel, Field


class BatchSummary(BaseModel):
    totale_file: int
    elaborati: int
    gia_presenti: int
    errori_formato: int
    anomalie_generate: int


class BatchResponse(BaseModel):
    batch_id: str
    stato: str
    riepilogo: BatchSummary
    non_whitelistati_fornitori: list[dict] = []
    non_registrate_location: list[dict] = []


class BatchFileError(BaseModel):
    nome_file: str
    codice_errore: str
    messaggio: str


class BatchDetailResponse(BaseModel):
    batch_id: str
    stato: str
    file_totali: int
    file_elaborati: int
    gia_presenti: int
    errori_formato: int
    anomalie_generate: int
    note: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    errori: list[BatchFileError] = []

    model_config = {"from_attributes": True}


class BatchHistoryItem(BaseModel):
    id: str
    created_at: datetime
    file_totali: int
    anomalie_generate: int
    stato: str
    note: str | None = None

    model_config = {"from_attributes": True}
