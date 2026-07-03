"""
Price Sentinel — Pipeline di Ingestion.
Sprint 2: orchestrazione completa dal XML raw al matching e generazione anomalie.

Spec §2.2 Steps 5-9:
  5. TipoDocumento routing (TD01/TD04/TD08)
  6. White-listing P.IVA fornitore
  7. TD01: parsing righe → matching → anomalie
  8. TD04: proposta chiusura anomalie aperte
  9. TD08: archiviazione passiva
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anomalie import Anomalia, StatoValidazione, NotaDiCredito
from app.models.fatture import (
    Fattura,
    RigaFattura,
    StatoMatching,
    TipoDocumento,
    XMLRaw,
    StatoIngestion,
)
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.services.matching import match_riga, MatchResult
from app.services.xml_parser import FatturaParsata, RigaParsata
from app.services.notifications import notify_manager_anomalies

logger = logging.getLogger("price_sentinel.ingestion")


async def process_xml_raw(db: AsyncSession, xml_raw_id: int, parsed: FatturaParsata) -> dict:
    """
    Pipeline completa di ingestion — Spec §2.2.

    Orchestrazione:
    1. Aggiorna stato XMLRaw
    2. Routing per TipoDocumento
    3. White-listing fornitore
    4. Creazione record Fattura + Righe
    5. Matching e generazione Anomalie
    6. Report risultato

    Returns:
        Dict con statistiche del processing
    """
    report = {
        "xml_raw_id": xml_raw_id,
        "tipo_documento": parsed.tipo_documento,
        "fornitore_piva": parsed.piva_cedente,
        "location_piva": parsed.piva_cessionario,
        "righe_totali": len(parsed.righe),
        "righe_matched": 0,
        "righe_parking": 0,
        "righe_omaggio": 0,
        "anomalie_generate": 0,
        "status": "success",
        "errori": [],
    }

    # ── Validazione parsing ──
    if not parsed.is_valid:
        await _set_xml_errore(db, xml_raw_id, "; ".join(parsed.errori))
        report["status"] = "parse_error"
        report["errori"] = parsed.errori
        return report

    # ── Step 6: White-listing P.IVA fornitore ──
    fornitore = await _resolve_fornitore(db, parsed.piva_cedente)
    if not fornitore:
        # Fornitore non in whitelist — archiviazione passiva (Spec §2.2 Step 6)
        await _set_xml_stato(db, xml_raw_id, StatoIngestion.parsato)
        report["status"] = "fornitore_non_whitelistato"
        return report

    if not fornitore.attivo_whitelist:
        await _set_xml_stato(db, xml_raw_id, StatoIngestion.parsato)
        report["status"] = "fornitore_disattivato"
        return report

    # ── Resolve Location ──
    location = await _resolve_location(db, parsed.piva_cessionario)
    if not location:
        await _set_xml_errore(db, xml_raw_id, f"Location con P.IVA {parsed.piva_cessionario} non trovata")
        report["status"] = "location_sconosciuta"
        report["errori"].append(f"P.IVA cessionario {parsed.piva_cessionario} non in anagrafica")
        return report

    # ── Step 5: Routing per TipoDocumento ──
    tipo = parsed.tipo_documento.upper()

    if tipo == "TD01":
        # Fattura standard — parsing completo + matching
        result = await _process_td01(db, xml_raw_id, parsed, fornitore, location)
        report.update(result)

    elif tipo == "TD04":
        # Nota di Credito fornitore — proposta chiusura anomalie
        result = await _process_td04(db, xml_raw_id, parsed, fornitore, location)
        report.update(result)

    elif tipo == "TD08":
        # Nota di Debito — archiviazione passiva con flag
        result = await _process_td08(db, xml_raw_id, parsed, fornitore, location)
        report.update(result)

    else:
        # Tipo non gestito — archiviazione passiva
        await _set_xml_stato(db, xml_raw_id, StatoIngestion.parsato)
        report["status"] = f"tipo_documento_non_gestito_{tipo}"

    # ── Aggiorna XMLRaw ──
    await _set_xml_stato(db, xml_raw_id, StatoIngestion.parsato)

    return report


# ─────────────────────────────────────────────
# TD01 — Fattura Standard (Spec §2.2 Step 7)
# ─────────────────────────────────────────────

async def _process_td01(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
) -> dict:
    """Processa una fattura TD01 — il flusso principale."""

    stats = {
        "righe_matched": 0,
        "righe_parking": 0,
        "righe_omaggio": 0,
        "anomalie_generate": 0,
    }

    # ── Crea record Fattura ──
    fattura = Fattura(
        xml_raw_id=xml_raw_id,
        fornitore_id=fornitore.id,
        location_id=location.id,
        numero_documento=parsed.numero_documento,
        data_documento=_parse_date(parsed.data_documento),
        data_ricezione_sdi=_parse_date(parsed.data_ricezione_sdi or parsed.data_documento),
        tipo_documento=TipoDocumento.TD01,
        totale_imponibile=parsed.totale_imponibile,
    )
    db.add(fattura)
    await db.flush()

    # ── Processa ogni riga ──
    for riga_parsed in parsed.righe:
        # Skip omaggi — Spec §3.3
        if riga_parsed.is_omaggio:
            stats["righe_omaggio"] += 1
            riga_db = _create_riga_fattura(fattura.id, riga_parsed, StatoMatching.matched, None)
            db.add(riga_db)
            continue

        # ── Matching Engine ──
        match_result = await match_riga(
            db=db,
            fornitore_id=fornitore.id,
            codice_articolo=riga_parsed.codice_articolo,
            tipo_codice=riga_parsed.tipo_codice,
            descrizione=riga_parsed.descrizione,
            prezzo_netto_normalizzato=riga_parsed.prezzo_netto_normalizzato,
            quantita=riga_parsed.quantita,
            unita_misura_fattura=riga_parsed.unita_misura,
            data_documento=parsed.data_documento,
        )

        if match_result.livello == 4:
            # Parking Area — Spec §3.1 Livello 4
            stato = StatoMatching.in_parking
            stats["righe_parking"] += 1
        elif match_result.livello == 3:
            # Fuzzy — proposta all'operatore
            stato = StatoMatching.in_parking
            stats["righe_parking"] += 1
        else:
            # Match confermato (Livello 1 o 2)
            stato = StatoMatching.matched
            stats["righe_matched"] += 1

        # ── Crea Riga Fattura ──
        riga_db = _create_riga_fattura(
            fattura.id, riga_parsed, stato, match_result.sku_interno
        )
        db.add(riga_db)
        await db.flush()

        # ── Salva Match Candidates per Review / Parking Area (Fase 1 / 6) ──
        if stato == StatoMatching.in_parking and getattr(match_result, "candidates", None):
            from app.models.products import MatchCandidate
            for c in match_result.candidates:
                candidate = MatchCandidate(
                    invoice_line_id=riga_db.id,
                    product_id=c["product_id"],
                    score=Decimal(str(c["score"])),
                    reason_json=c["reason_json"],
                )
                db.add(candidate)
            await db.flush()

        # ── Genera Anomalia se Delta > 0 — Spec §4.1 ──
        if match_result.matched and match_result.delta_prezzo > Decimal("0"):
            anomalia = Anomalia(
                riga_fattura_id=riga_db.id,
                delta_prezzo=match_result.delta_prezzo,
                delta_totale=match_result.delta_totale,
                prezzo_listino_snapshot=match_result.prezzo_listino,
                prezzo_fatturato_snapshot=match_result.prezzo_fatturato_normalizzato,
                stato_validazione=StatoValidazione.da_verificare,
            )
            db.add(anomalia)
            stats["anomalie_generate"] += 1

    # ── Telegram Notification ──
    if stats["anomalie_generate"] > 0:
        # Trova il manager della location
        from app.models.utenti import Utente, RuoloUtente
        manager_res = await db.execute(
            select(Utente).where(
                and_(Utente.location_id == location.id, Utente.ruolo == RuoloUtente.manager)
            )
        )
        manager = manager_res.scalar_one_or_none()
        if manager and manager.telegram_chat_id:
            import asyncio
            asyncio.create_task(
                notify_manager_anomalies(
                    chat_id=manager.telegram_chat_id,
                    location_name=location.nome_struttura,
                    count=stats["anomalie_generate"],
                    fornitore_nome=fornitore.nome_azienda,
                )
            )

    return stats


# ─────────────────────────────────────────────
# TD04 — Nota di Credito (Spec §2.2 Step 8)
# ─────────────────────────────────────────────

async def _process_td04(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
) -> dict:
    """
    Nota di credito da fornitore — cerca anomalie aperte
    e le propone per chiusura automatica.
    """
    from app.models.anomalie import Anomalia, StatoValidazione, NotaDiCredito
    from app.models.fatture import RigaFattura
    from datetime import date as date_type

    fattura = Fattura(
        xml_raw_id=xml_raw_id,
        fornitore_id=fornitore.id,
        location_id=location.id,
        numero_documento=parsed.numero_documento,
        data_documento=_parse_date(parsed.data_documento),
        data_ricezione_sdi=_parse_date(parsed.data_ricezione_sdi or parsed.data_documento),
        tipo_documento=TipoDocumento.TD04,
        totale_imponibile=parsed.totale_imponibile,
    )
    db.add(fattura)
    await db.flush()

    # Salva le righe per reference e prova ad abbinare gli SKU
    from app.services.matching import match_riga
    for riga_parsed in parsed.righe:
        sku = None
        stato = StatoMatching.no_match
        
        try:
            match_res = await match_riga(
                db=db,
                fornitore_id=fornitore.id,
                codice_articolo=riga_parsed.codice_articolo,
                tipo_codice=riga_parsed.tipo_codice,
                descrizione=riga_parsed.descrizione,
                prezzo_netto_normalizzato=riga_parsed.prezzo_netto_normalizzato,
                quantita=riga_parsed.quantita,
                unita_misura_fattura=riga_parsed.unita_misura,
                data_documento=parsed.data_documento,
            )
            if match_res.matched:
                sku = match_res.sku_interno
                stato = StatoMatching.matched
        except Exception as e:
            # Fallback safe
            pass
            
        riga_db = _create_riga_fattura(fattura.id, riga_parsed, stato, sku)
        db.add(riga_db)

    # ── Caricamento Anomalie Aperte dello stesso Fornitore e Location ──
    from sqlalchemy.orm import selectinload
    anomalie_query = (
        select(Anomalia)
        .options(selectinload(Anomalia.riga_fattura))
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(
            and_(
                Fattura.fornitore_id == fornitore.id,
                Fattura.location_id == location.id,
                Anomalia.stato_validazione.in_([
                    StatoValidazione.da_verificare,
                    StatoValidazione.in_parking,
                    StatoValidazione.contestata,
                    StatoValidazione.in_reclamo,
                ])
            )
        )
    )
    res = await db.execute(anomalie_query)
    pending_anomalies = list(res.scalars().all())

    reconciled_count = 0
    total_reconciled_amount = Decimal("0")

    # ── Reconciliation Algorithm ──
    for riga_parsed in parsed.righe:
        # Importo totale del credito per questa riga
        credito_valore = abs(riga_parsed.prezzo_netto_normalizzato * riga_parsed.quantita)
        if credito_valore == Decimal("0"):
            continue

        matched_anomalia = None

        # 1. Trova anomalia per codice articolo
        if riga_parsed.codice_articolo:
            for anom in pending_anomalies:
                if anom.riga_fattura and anom.riga_fattura.codice_fornitore_raw == riga_parsed.codice_articolo:
                    matched_anomalia = anom
                    break

        # 2. Fallback su descrizione simile
        if not matched_anomalia and riga_parsed.descrizione:
            desc_clean = riga_parsed.descrizione.strip().lower()
            for anom in pending_anomalies:
                if anom.riga_fattura and anom.riga_fattura.descrizione_fornitore_raw:
                    anom_desc = anom.riga_fattura.descrizione_fornitore_raw.strip().lower()
                    if desc_clean in anom_desc or anom_desc in desc_clean:
                        matched_anomalia = anom
                        break

        # Se troviamo un match, effettuiamo lo storno e segniamo l'anomalia come risolta
        if matched_anomalia:
            importo_recuperato = min(credito_valore, Decimal(str(matched_anomalia.delta_totale)))
            
            # Trova l'id di un admin esistente nel database (evitando fk crash se seq > 1)
            from app.models.utenti import Utente, RuoloUtente
            admin_res = await db.execute(
                select(Utente.id).where(Utente.ruolo == RuoloUtente.admin).limit(1)
            )
            admin_id = admin_res.scalar() or 1

            # Crea il record NotaDiCredito nel DB
            nc_record = NotaDiCredito(
                anomalia_id=matched_anomalia.id,
                importo_recuperato=float(importo_recuperato),
                data_emissione_nc=fattura.data_documento,
                data_registrazione=date_type.today(),
                numero_nc=fattura.numero_documento,
                registrato_da_admin_id=admin_id,
            )
            db.add(nc_record)

            # Transizione dello stato a risolta
            matched_anomalia.stato_validazione = StatoValidazione.risolta
            
            # Rimuovi dalla lista dei pendenti per evitare doppi matching
            pending_anomalies.remove(matched_anomalia)
            reconciled_count += 1
            total_reconciled_amount += importo_recuperato

    return {
        "status": "td04_registrata",
        "fattura_id": fattura.id,
        "anomalie_riconciliate": reconciled_count,
        "totale_recuperato": float(total_reconciled_amount)
    }


# ─────────────────────────────────────────────
# TD08 — Nota di Debito (Spec §2.2 Step 9)
# ─────────────────────────────────────────────

async def _process_td08(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
) -> dict:
    """Nota di debito — archiviazione passiva con flag per revisione manuale."""
    fattura = Fattura(
        xml_raw_id=xml_raw_id,
        fornitore_id=fornitore.id,
        location_id=location.id,
        numero_documento=parsed.numero_documento,
        data_documento=_parse_date(parsed.data_documento),
        data_ricezione_sdi=_parse_date(parsed.data_ricezione_sdi or parsed.data_documento),
        tipo_documento=TipoDocumento.TD08,
        totale_imponibile=parsed.totale_imponibile,
    )
    db.add(fattura)
    await db.flush()

    for riga_parsed in parsed.righe:
        riga_db = _create_riga_fattura(fattura.id, riga_parsed, StatoMatching.matched, None)
        db.add(riga_db)

    return {"status": "td08_archiviata", "fattura_id": fattura.id}


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

async def _resolve_fornitore(db: AsyncSession, piva: str) -> Fornitore | None:
    """Trova il fornitore per P.IVA."""
    result = await db.execute(
        select(Fornitore).where(Fornitore.partita_iva == piva)
    )
    return result.scalar_one_or_none()


async def _resolve_location(db: AsyncSession, piva: str) -> Location | None:
    """Trova la location per P.IVA cessionario."""
    result = await db.execute(
        select(Location).where(Location.piva_riferimento == piva)
    )
    return result.scalar_one_or_none()


async def _set_xml_stato(db: AsyncSession, xml_raw_id: int, stato: StatoIngestion):
    """Aggiorna lo stato di ingestion dell'XMLRaw."""
    await db.execute(
        update(XMLRaw).where(XMLRaw.id == xml_raw_id).values(stato_ingestion=stato)
    )


async def _set_xml_errore(db: AsyncSession, xml_raw_id: int, errore: str):
    """Segna l'XMLRaw come errore con dettaglio."""
    await db.execute(
        update(XMLRaw)
        .where(XMLRaw.id == xml_raw_id)
        .values(stato_ingestion=StatoIngestion.errore, errore_dettaglio=errore)
    )


def _create_riga_fattura(
    fattura_id: int,
    riga: RigaParsata,
    stato: StatoMatching,
    sku: str | None,
) -> RigaFattura:
    """Crea il record RigaFattura dal parsing."""
    return RigaFattura(
        fattura_id=fattura_id,
        numero_linea=riga.numero_linea,
        codice_fornitore_raw=riga.codice_articolo,
        descrizione_fornitore_raw=riga.descrizione,
        sku_interno=sku,
        prezzo_unitario_fatturato=riga.prezzo_unitario,
        sconto_percentuale=riga.sconto_percentuale,
        prezzo_netto_normalizzato=riga.prezzo_netto_normalizzato,
        quantita=riga.quantita,
        unita_misura_fattura=riga.unita_misura,
        aliquota_iva=riga.aliquota_iva,
        is_omaggio=riga.is_omaggio,
        stato_matching=stato,
    )


def _parse_date(date_str: str) -> date:
    """Parse date string in vari formati."""
    if not date_str:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return date.today()
