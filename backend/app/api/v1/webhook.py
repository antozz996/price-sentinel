"""
Price Sentinel — Webhook Aruba Router.
Sprint 2: Endpoint completo con parsing XML e pipeline di ingestion.
Spec §2.1, §2.2.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_aruba_api_key
from app.database import get_db
from app.models.fatture import XMLRaw, StatoIngestion
from app.schemas.fatture import WebhookArubaPayload
from app.services.ingestion import process_xml_raw
from app.services.xml_parser import (
    calcola_hash_idempotenza,
    decode_xml_base64,
    parse_fattura_xml,
)

router = APIRouter()


@router.post(
    "/aruba",
    status_code=status.HTTP_200_OK,
    summary="Webhook ricezione fatture Aruba",
    description=(
        "Endpoint invocato da Aruba in tempo reale (PUSH) alla ricezione "
        "di una nuova fattura elettronica dal SDI. "
        "Sprint 2: parsing completo + matching + generazione anomalie. "
        "API Key obbligatoria — Spec §1.2, §2.2"
    ),
    dependencies=[Depends(verify_aruba_api_key)],
)
async def webhook_aruba(
    payload: WebhookArubaPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Workflow di Ingestion completo — Spec §2.2:
    1. API Key validata dal dependency
    2. Decodifica XML da Base64
    3. Parsing XML FatturaPA
    4. Hash idempotenza su (P.IVA + numero + data) — Spec §2.2 Step 3
    5. Salvataggio XMLRaw
    6. Pipeline: routing TD → whitelisting → matching → anomalie
    """

    # ── Step 2: Decodifica Base64 ──
    try:
        xml_string = decode_xml_base64(payload.xml_base64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload Base64 non valido",
        )

    # ── Step 3: Parsing XML ──
    parsed = parse_fattura_xml(xml_string)

    # ── Step 4: Hash idempotenza ──
    if parsed.is_valid:
        hash_idempotenza = calcola_hash_idempotenza(
            parsed.piva_cedente,
            parsed.numero_documento,
            parsed.data_documento,
        )
    else:
        # Fallback: hash dell'intero payload
        hash_idempotenza = hashlib.sha256(xml_string.encode("utf-8")).hexdigest()

    # ── Idempotenza check ──
    existing = await db.execute(
        select(XMLRaw).where(XMLRaw.hash_idempotenza == hash_idempotenza)
    )
    if existing.scalar_one_or_none():
        return {"status": "already_processed", "hash": hash_idempotenza}

    # ── Step 5: Salva XMLRaw ──
    xml_raw = XMLRaw(
        payload=xml_string,
        nome_file=payload.nome_file,
        hash_idempotenza=hash_idempotenza,
        stato_ingestion=StatoIngestion.ricevuto,
        data_ricezione=datetime.now(timezone.utc),
    )
    db.add(xml_raw)
    await db.flush()

    # ── Step 6: Pipeline completa ──
    report = await process_xml_raw(db, xml_raw.id, parsed)

    return {
        "status": report.get("status", "processed"),
        "xml_raw_id": xml_raw.id,
        "hash": hash_idempotenza,
        "tipo_documento": report.get("tipo_documento"),
        "righe_totali": report.get("righe_totali", 0),
        "righe_matched": report.get("righe_matched", 0),
        "righe_parking": report.get("righe_parking", 0),
        "anomalie_generate": report.get("anomalie_generate", 0),
    }
