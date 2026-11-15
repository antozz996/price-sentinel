"""
Price Sentinel — Pipeline di Ingestion.
Sprint 2: orchestrazione completa dal XML raw al matching e generazione anomalie.

Spec §2.2 Steps 5-9:
  5. TipoDocumento routing (TD01/TD04/TD08)
  6. White-listing P.IVA fornitore
  7. TD01: parsing righe → matching → anomalie
  8. TD04: proposta chiusura anomalie aperte (avviso, nessuna chiusura automatica)
  9. TD08 (nota di credito semplificata): stesso trattamento della TD04
"""

import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, and_, func, update
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
from app.services.normalization import normalize_text
from app.services.xml_parser import FatturaParsata, RigaParsata
from app.services.notifications import notify_manager_anomalies
from app.services.purchase_lines import CREDIT_NOTE_TYPES

logger = logging.getLogger("price_sentinel.ingestion")

# Stato restituito quando l'XML ha già una fattura: chi chiama lo conta come
# "già presente" e non come nuova elaborazione.
STATUS_GIA_PRESENTE = "gia_presente"


async def lock_xml_raw_and_find_fattura(db: AsyncSession, xml_raw_id: int) -> int | None:
    """Blocca la riga xml_raw (FOR UPDATE) e restituisce l'id della fattura già creata, se c'è.

    Il lock dura fino alla fine della transazione esterna, quindi copre anche la
    creazione della fattura fatta subito dopo dallo stesso chiamante.
    """
    await db.execute(
        select(XMLRaw.id).where(XMLRaw.id == xml_raw_id).with_for_update()
    )
    return await db.scalar(
        select(Fattura.id)
        .where(Fattura.xml_raw_id == xml_raw_id)
        .order_by(Fattura.id)
        .limit(1)
    )


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

    # ── Idempotenza: un XML produce al massimo una fattura ──
    # Il lock sulla riga xml_raw serializza due elaborazioni concorrenti dello
    # stesso XML (upload doppio, reprocess in parallelo): la seconda attende,
    # trova la fattura creata dalla prima e si ferma senza duplicarla.
    existing_fattura_id = await lock_xml_raw_and_find_fattura(db, xml_raw_id)
    if existing_fattura_id is not None:
        report["status"] = STATUS_GIA_PRESENTE
        report["fattura_id"] = existing_fattura_id
        return report

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

    if tipo in ("TD01", "TD24", "TD25"):
        # Fattura standard o differita — parsing completo + matching
        result = await _process_td01(db, xml_raw_id, parsed, fornitore, location)
        report.update(result)

    elif tipo == "TD04":
        # Nota di Credito fornitore — solo proposta di chiusura anomalie
        result = await _process_td04(db, xml_raw_id, parsed, fornitore, location)
        report.update(result)

    elif tipo == "TD08":
        # Nota di credito semplificata (SdI): stesso trattamento della TD04
        # (righe, matching, proposta di chiusura); nelle analisi segno -1.
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
# TD01 / TD24 — Fattura Standard / Differita (Spec §2.2 Step 7)
# ─────────────────────────────────────────────

async def _process_td01(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
) -> dict:
    """Processa una fattura TD01/TD24/TD25 — il flusso principale."""

    stats = {
        "righe_matched": 0,
        "righe_parking": 0,
        "righe_omaggio": 0,
        "anomalie_generate": 0,
    }

    doc_type = getattr(TipoDocumento, parsed.tipo_documento.upper(), TipoDocumento.TD01)

    # ── Crea record Fattura ──
    fattura = Fattura(
        xml_raw_id=xml_raw_id,
        fornitore_id=fornitore.id,
        location_id=location.id,
        numero_documento=parsed.numero_documento,
        data_documento=_parse_date(parsed.data_documento),
        data_ricezione_sdi=_parse_date(parsed.data_ricezione_sdi or parsed.data_documento),
        tipo_documento=doc_type,
        totale_imponibile=parsed.totale_imponibile,
    )
    db.add(fattura)
    await db.flush()

    # ── Processa ogni riga ──
    non_product_cache: dict[str, bool] = {}
    for riga_parsed in parsed.righe:
        # Skip omaggi — Spec §3.3
        if riga_parsed.is_omaggio:
            stats["righe_omaggio"] += 1
            riga_db = _create_riga_fattura(fattura.id, riga_parsed, StatoMatching.matched, None)
            db.add(riga_db)
            continue

        # Charges already filed as "not a product" for this supplier (transport,
        # office fees…) come back on every invoice: file them the same way.
        if await _is_known_non_product(db, fornitore.id, riga_parsed, non_product_cache):
            db.add(_create_riga_fattura(fattura.id, riga_parsed, StatoMatching.no_match, None))
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

        if match_result.matched and match_result.livello in (1, 2) and match_result.decision == "auto_match":
            # Match confermato con listino attivo (Livello 1 o 2)
            stato = StatoMatching.matched
            stats["righe_matched"] += 1
        elif match_result.senza_listino:
            # Known product, no price agreement on the invoice date: linked
            # to the product, with no price check and therefore no anomaly.
            stato = StatoMatching.matched
            stats["righe_matched"] += 1
        else:
            # Parking Area / Needs Review / No Listino — Spec §3.1 Livello 3 o 4
            stato = StatoMatching.in_parking
            stats["righe_parking"] += 1

        # ── Crea Riga Fattura ──
        riga_db = _create_riga_fattura(
            fattura.id, riga_parsed, stato, match_result.sku_interno
        )
        db.add(riga_db)
        await db.flush()

        # ── Salva Match Candidates per Review / Parking Area (Fase 1 / 6) ──
        if stato == StatoMatching.in_parking and getattr(match_result, "candidates", None):
            from app.models.products import MatchCandidate
            # Le somiglianze deboli non sono proposte operative: la riga resta
            # nella work queue come probabile nuovo prodotto, senza creare cinque
            # falsi match da rifiutare manualmente.
            review_candidates = [
                candidate
                for candidate in match_result.candidates
                if candidate["score"] >= 70
                and not candidate["block"]
                and candidate["decision"] == "needs_review"
            ][:3]
            for c in review_candidates:
                candidate = MatchCandidate(
                    invoice_line_id=riga_db.id,
                    product_id=c["product_id"],
                    supplier_id=fornitore.id,
                    raw_description=riga_parsed.descrizione,
                    normalized_description=normalize_text(riga_parsed.descrizione),
                    score=Decimal(str(c["score"])),
                    reason_json=c["reason_json"],
                    block_flag=c["block"],
                )
                db.add(candidate)
            await db.flush()

        # Ignore sub-cent rounding noise: an operational anomaly starts only
        # when the total overcharge exceeds the shared materiality threshold
        # and the unit gap is not mere rounding.
        from app.services.anomaly_policy import invoice_in_check_scope, is_material_price_increase
        if (
            match_result.matched
            and is_material_price_increase(match_result.delta_totale, match_result.delta_prezzo)
            and await invoice_in_check_scope(db, xml_raw_id)
        ):
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
# TD04 / TD08 — Note di Credito (Spec §2.2 Step 8-9)
# ─────────────────────────────────────────────

# Avviso operativo creato per ogni abbinamento proposto tra una nota di credito
# importata e un'anomalia aperta. Non e' tra i tipi gestiti dal monitor: resta
# finche' qualcuno non lo prende in carico.
CREDIT_NOTE_PROPOSAL_ALERT = "credit_note_proposal"

# Anomalie che una nota di credito potrebbe riguardare (stessi stati di prima).
CREDIT_NOTE_PROPOSAL_STATES = (
    StatoValidazione.da_verificare,
    StatoValidazione.in_parking,
    StatoValidazione.contestata,
    StatoValidazione.in_reclamo,
)


def propose_credit_note_matches(righe, pending_anomalies) -> list[dict]:
    """Abbina le righe di una nota di credito alle anomalie aperte, senza decidere nulla.

    Per codice articolo e, in mancanza, per descrizione contenuta (come prima).
    Ogni anomalia compare al massimo una volta. Il valore della riga e' il netto
    di fattura della base comune (pu x (1 - sconto/100) x quantita), in positivo.
    """
    from app.services.purchase_lines import line_net_unit_price

    pending = list(pending_anomalies)
    proposals: list[dict] = []
    for riga in righe:
        valore = abs(
            line_net_unit_price(riga.prezzo_unitario, riga.sconto_percentuale)
            * Decimal(str(riga.quantita or 0))
        )
        if valore == Decimal("0"):
            continue
        matched, how = None, None
        if riga.codice_articolo:
            matched = next(
                (
                    anom for anom in pending
                    if anom.riga_fattura
                    and anom.riga_fattura.codice_fornitore_raw == riga.codice_articolo
                ),
                None,
            )
            how = "codice" if matched else None
        if matched is None and riga.descrizione:
            desc_clean = riga.descrizione.strip().lower()
            for anom in pending:
                anom_desc = ((anom.riga_fattura.descrizione_fornitore_raw if anom.riga_fattura else None) or "").strip().lower()
                if desc_clean and anom_desc and (desc_clean in anom_desc or anom_desc in desc_clean):
                    matched, how = anom, "descrizione"
                    break
        if matched is None:
            continue
        pending.remove(matched)
        proposals.append({
            "anomalia_id": matched.id,
            "abbinamento": how,
            "riga_nota": riga.numero_linea,
            "descrizione_nota": riga.descrizione,
            "valore_riga_nota": str(valore.quantize(Decimal("0.01"))),
            "rincaro_anomalia": str(Decimal(str(matched.delta_totale)).quantize(Decimal("0.01"))),
            "descrizione_anomalia": matched.riga_fattura.descrizione_fornitore_raw if matched.riga_fattura else None,
        })
    return proposals


async def _process_td04(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
    tipo_documento: TipoDocumento = TipoDocumento.TD04,
) -> dict:
    """
    Nota di credito da fornitore (TD04, o TD08 semplificata con lo stesso trattamento).

    Registra la nota e le righe e cerca le anomalie aperte dello stesso fornitore
    e sede che potrebbe riguardare. NON chiude nessuna anomalia e non crea
    NotaDiCredito: una nota di credito e' quasi sempre un reso di merce
    (es. "Vs Reso Ns Fattura n. 136"), non lo storno del rincaro, e prima un
    reso chiudeva l'anomalia come "risolta" gonfiando "Soldi recuperati".
    Ogni abbinamento diventa una proposta (avviso operativo); la nota si
    registra a mano nella pratica di contestazione.
    """
    from sqlalchemy.orm import selectinload
    from app.models.automation import AutomationAlert
    from app.services.anomaly_policy import operational_anomaly_filter
    from app.services.matching import match_riga

    fattura = Fattura(
        xml_raw_id=xml_raw_id,
        fornitore_id=fornitore.id,
        location_id=location.id,
        numero_documento=parsed.numero_documento,
        data_documento=_parse_date(parsed.data_documento),
        data_ricezione_sdi=_parse_date(parsed.data_ricezione_sdi or parsed.data_documento),
        tipo_documento=tipo_documento,
        totale_imponibile=parsed.totale_imponibile,
    )
    db.add(fattura)
    await db.flush()

    # Salva le righe per reference e prova ad abbinare gli SKU
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
            if match_res.matched or match_res.senza_listino:
                sku = match_res.sku_interno
                stato = StatoMatching.matched
        except Exception:
            # Fallback safe: la riga resta senza SKU
            pass
        db.add(_create_riga_fattura(fattura.id, riga_parsed, stato, sku))

    # ── Anomalie aperte dello stesso fornitore e sede ──
    anomalie_query = (
        select(Anomalia)
        .options(selectinload(Anomalia.riga_fattura))
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(
            and_(
                Fattura.fornitore_id == fornitore.id,
                Fattura.location_id == location.id,
                Anomalia.stato_validazione.in_(CREDIT_NOTE_PROPOSAL_STATES),
                # Niente proposte sul rumore di arrotondamento mai lavorato.
                operational_anomaly_filter(),
            )
        )
        .order_by(Anomalia.id)
    )
    pending_anomalies = list((await db.execute(anomalie_query)).scalars().all())
    proposals = propose_credit_note_matches(parsed.righe, pending_anomalies)

    now = datetime.now(timezone.utc)
    tipo = tipo_documento.value
    for proposal in proposals:
        db.add(
            AutomationAlert(
                dedupe_key=f"{CREDIT_NOTE_PROPOSAL_ALERT}:{fattura.id}:{proposal['anomalia_id']}",
                alert_type=CREDIT_NOTE_PROPOSAL_ALERT,
                severity="info",
                status="open",
                location_id=location.id,
                entity_type="anomaly",
                entity_id=str(proposal["anomalia_id"]),
                title="Nota di credito da verificare",
                message=(
                    f"La nota di credito {tipo} n. {fattura.numero_documento} del "
                    f"{fattura.data_documento:%d/%m/%Y} potrebbe riguardare l'anomalia "
                    f"#{proposal['anomalia_id']} (rincaro € {proposal['rincaro_anomalia']}, "
                    f"riga nota € {proposal['valore_riga_nota']}). Nessuna chiusura "
                    "automatica: se storna il rincaro, registrala nella pratica di contestazione."
                ),
                details={"fattura_id": fattura.id, "tipo_documento": tipo, **proposal},
                first_detected_at=now,
                last_detected_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    return {
        "status": f"{tipo.lower()}_registrata",
        "fattura_id": fattura.id,
        "anomalie_riconciliate": 0,
        "proposte_chiusura": proposals,
    }


async def _process_td08(
    db: AsyncSession,
    xml_raw_id: int,
    parsed: FatturaParsata,
    fornitore: Fornitore,
    location: Location,
) -> dict:
    """Nota di credito semplificata (SdI): stesso trattamento della TD04."""
    return await _process_td04(
        db, xml_raw_id, parsed, fornitore, location, tipo_documento=TipoDocumento.TD08
    )


# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

async def _resolve_fornitore(db: AsyncSession, piva: str) -> Fornitore | None:
    """Trova il fornitore per P.IVA (con o senza prefisso nazione)."""
    clean_piva = piva.strip().replace(" ", "").upper()
    candidates = [clean_piva]
    if clean_piva.startswith("IT") and len(clean_piva) > 2:
        candidates.append(clean_piva[2:])
    elif not clean_piva.startswith("IT"):
        candidates.append(f"IT{clean_piva}")

    result = await db.execute(
        select(Fornitore).where(Fornitore.partita_iva.in_(candidates))
    )
    return result.scalar_one_or_none()


async def _resolve_location(db: AsyncSession, piva: str) -> Location | None:
    """Trova la location per P.IVA cessionario (con o senza prefisso nazione)."""
    clean_piva = piva.strip().replace(" ", "").upper()
    candidates = [clean_piva]
    if clean_piva.startswith("IT") and len(clean_piva) > 2:
        candidates.append(clean_piva[2:])
    elif not clean_piva.startswith("IT"):
        candidates.append(f"IT{clean_piva}")

    result = await db.execute(
        select(Location).where(Location.piva_riferimento.in_(candidates))
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

async def _is_known_non_product(db: AsyncSession, fornitore_id: int, riga, cache: dict[str, bool]) -> bool:
    """A code-less line whose description this supplier already had filed as no_match.

    Digits are ignored, so a delivery-note total ("DDT N 4679/26 DEL 17/04/2026")
    matches the ones filed before it. Credit notes are left out: their lines are
    no_match by default, not by choice.
    """
    exact = (riga.descrizione or "").strip().lower()
    description = re.sub(r"\d+", "#", exact)
    if riga.codice_articolo or not exact:
        return False
    if exact not in cache:
        archived = (
            select(RigaFattura.descrizione_fornitore_raw)
            .join(Fattura, Fattura.id == RigaFattura.fattura_id)
            .where(
                Fattura.fornitore_id == fornitore_id,
                Fattura.tipo_documento.notin_(CREDIT_NOTE_TYPES),
                RigaFattura.stato_matching == StatoMatching.no_match,
                func.coalesce(RigaFattura.codice_fornitore_raw, "") == "",
            )
        )
        same_text = func.lower(func.btrim(RigaFattura.descrizione_fornitore_raw))
        if await db.scalar(archived.where(same_text == exact).limit(1)) is not None:
            cache[exact] = True
        else:
            # Without the digits a wrongly filed product would drag its other sizes
            # along: ask for a habit (three lines filed), not a single precedent.
            same_shape = (await db.scalars(
                archived.where(func.regexp_replace(same_text, "[0-9]+", "#", "g") == description).limit(3)
            )).all()
            cache[exact] = description != exact and len(same_shape) >= 3
    return cache[exact]
