import uuid
import zipfile
import io
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.utenti import Utente, RuoloUtente
from app.models.fatture import (
    XMLRaw, 
    UploadBatch, 
    StatoBatch, 
    SourceIngestion, 
    StatoIngestion
)
from app.schemas.ingestion import (
    BatchResponse, 
    BatchDetailResponse, 
    BatchHistoryItem,
    BatchSummary
)
from app.services.ingestion import process_xml_raw
from app.services.xml_parser import (
    parse_fattura_xml, 
    calcola_hash_idempotenza, 
    decode_xml_base64
)

logger = logging.getLogger("price_sentinel.api.ingestion")
router = APIRouter()


@router.post(
    "/upload",
    response_model=BatchResponse,
    summary="Upload manuale fatture XML o ZIP",
    description="Permette ai Manager di caricare file XML o archivi ZIP. Spec Sprint 1 Extension."
)
async def upload_fatture(
    files: List[UploadFile] = File(...),
    note: str | None = Form(None),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Crea Batch
    batch_id = str(uuid.uuid4())
    batch = UploadBatch(
        id=batch_id,
        location_id=current_user.location_id,
        user_id=current_user.id,
        stato=StatoBatch.in_elaborazione,
        note=note,
        file_totali=0,
        file_elaborati=0,
        gia_presenti=0,
        errori_formato=0,
        anomalie_generate=0
    )
    db.add(batch)
    await db.flush()

    xml_files_to_process = []

    # 2. Estrai file (gestione ZIP)
    for upload_file in files:
        content = await upload_file.read()
        
        if upload_file.filename.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for info in z.infolist():
                        if not info.is_dir() and info.filename.lower().endswith('.xml') and not info.filename.startswith('__MACOSX'):
                            xml_content = z.read(info.filename).decode('utf-8-sig', errors='ignore')
                            xml_files_to_process.append((info.filename, xml_content))
            except zipfile.BadZipFile:
                batch.errori_formato += 1
                logger.warning(f"File {upload_file.filename} non è uno ZIP valido")
        
        elif upload_file.filename.lower().endswith('.xml'):
            try:
                xml_content = content.decode('utf-8-sig', errors='ignore')
                xml_files_to_process.append((upload_file.filename, xml_content))
            except Exception:
                batch.errori_formato += 1
                logger.warning(f"File {upload_file.filename} non è un XML leggibile")
        
        else:
            batch.errori_formato += 1
            logger.warning(f"File {upload_file.filename} estensione non supportata")

    batch.file_totali = len(xml_files_to_process) + batch.errori_formato
    await db.flush()

    non_whitelistati_fornitori = []
    non_registrate_location = []

    # 3. Processa XML
    for filename, xml_payload in xml_files_to_process:
        try:
            # Parsing base per idempotenza
            parsed = parse_fattura_xml(xml_payload)
            
            if not parsed.is_valid:
                batch.errori_formato += 1
                batch.file_elaborati += 1
                continue

            # Idempotenza
            hash_id = calcola_hash_idempotenza(
                parsed.piva_cedente, 
                parsed.numero_documento, 
                parsed.data_documento
            )
            
            existing = await db.execute(
                select(XMLRaw).where(XMLRaw.hash_idempotenza == hash_id)
            )
            if existing.scalar_one_or_none():
                batch.gia_presenti += 1
                batch.file_elaborati += 1
                continue

            from sqlalchemy.exc import IntegrityError
            try:
                # Salvataggio XMLRaw
                xml_raw = XMLRaw(
                    payload=xml_payload,
                    nome_file=filename,
                    hash_idempotenza=hash_id,
                    source=SourceIngestion.upload_manuale,
                    upload_batch_id=batch_id,
                    uploaded_by_user_id=current_user.id,
                    stato_ingestion=StatoIngestion.ricevuto,
                    data_ricezione=datetime.now(timezone.utc)
                )
                db.add(xml_raw)
                await db.flush()

                # Pipeline Matching
                report = await process_xml_raw(db, xml_raw.id, parsed)
                
                status_report = report.get("status")
                if status_report == "fornitore_non_whitelistato":
                    piva = parsed.piva_cedente
                    nome = parsed.denominazione_cedente or "Fornitore Sconosciuto"
                    if not any(f["partita_iva"] == piva for f in non_whitelistati_fornitori):
                        non_whitelistati_fornitori.append({"partita_iva": piva, "nome_azienda": nome})
                
                elif status_report == "location_sconosciuta":
                    piva = parsed.piva_cessionario
                    nome = f"Sede Gruppo P.IVA {piva}"
                    if not any(l["partita_iva"] == piva for l in non_registrate_location):
                        non_registrate_location.append({"partita_iva": piva, "nome_struttura": nome})

                batch.file_elaborati += 1
                batch.anomalie_generate += report.get("anomalie_generate", 0)
            except IntegrityError:
                await db.rollback()
                batch.gia_presenti += 1
                batch.file_elaborati += 1
                logger.info(f"File {filename} già presente (concorrenza rilevata via IntegrityError)")
                continue
            
        except Exception as e:
            logger.error(f"Errore durante processamento {filename}: {e}")
            batch.errori_formato += 1
            batch.file_elaborati += 1

    # 4. Finalizza Batch
    batch.stato = StatoBatch.completato if batch.errori_formato == 0 else StatoBatch.completato_con_errori
    batch.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return BatchResponse(
        batch_id=batch_id,
        stato=batch.stato.value,
        riepilogo=BatchSummary(
            totale_file=batch.file_totali,
            elaborati=batch.file_elaborati,
            gia_presenti=batch.gia_presenti,
            errori_formato=batch.errori_formato,
            anomalie_generate=batch.anomalie_generate
        ),
        non_whitelistati_fornitori=non_whitelistati_fornitori,
        non_registrate_location=non_registrate_location
    )


@router.get("/batch/{batch_id}", response_model=BatchDetailResponse)
async def get_batch_detail(
    batch_id: str,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(UploadBatch).where(UploadBatch.id == batch_id)
    if current_user.ruolo != RuoloUtente.admin:
        query = query.where(UploadBatch.location_id == current_user.location_id)
    
    res = await db.execute(query)
    batch = res.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch non trovato")
    
    return batch


@router.get("/uploads", response_model=List[BatchHistoryItem])
async def get_uploads_history(
    limit: int = 20,
    offset: int = 0,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(UploadBatch).order_by(desc(UploadBatch.created_at))
    if current_user.ruolo != RuoloUtente.admin:
        query = query.where(UploadBatch.location_id == current_user.location_id)
    
    query = query.limit(limit).offset(offset)
    res = await db.execute(query)
    return res.scalars().all()
