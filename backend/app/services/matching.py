"""
Price Sentinel — Motore di Matching a 4 Livelli.
Sprint 2: Pipeline cascata per abbinamento righe fattura → listino master.

Spec §3.1:
  Livello 1: Match esatto CodiceArticolo → Alias
  Livello 2: Match su EAN/barcode
  Livello 3: Fuzzy match testuale (Levenshtein) su Descrizione
  Livello 4: Nessun match → Parking Area

Spec §3.2: Conversione UoM automatica
Spec §3.3: Gestione Omaggi (skip anomalia)
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alias import AliasProdotto
from app.models.listino import ListinoMaster, UoMConversione


# ─────────────────────────────────────────────
# Result Types
# ─────────────────────────────────────────────

@dataclass
class MatchResult:
    """Risultato del matching per una singola riga fattura."""
    matched: bool = False
    livello: int = 0               # 1-4
    sku_interno: str | None = None
    listino_id: int | None = None
    prezzo_listino: Decimal = Decimal("0")
    prezzo_fatturato_normalizzato: Decimal = Decimal("0")
    delta_prezzo: Decimal = Decimal("0")      # Differenza per unità
    delta_totale: Decimal = Decimal("0")      # Delta * quantità
    coefficiente_uom: Decimal = Decimal("1")  # Conversione UoM applicata
    confidenza: float = 0.0                   # 0-1 per fuzzy match
    suggerimento_sku: str | None = None       # Per Livello 3
    suggerimento_desc: str | None = None      # Descrizione del suggerimento


FUZZY_THRESHOLD = 0.65  # Soglia minima per proporre un match fuzzy


async def match_riga(
    db: AsyncSession,
    fornitore_id: int,
    codice_articolo: str | None,
    tipo_codice: str | None,
    descrizione: str,
    prezzo_netto_normalizzato: Decimal,
    quantita: Decimal,
    unita_misura_fattura: str | None,
    data_documento: str,
) -> MatchResult:
    """
    Pipeline di matching a 4 livelli — Spec §3.1.

    Args:
        db: Sessione database
        fornitore_id: ID del fornitore in whitelist
        codice_articolo: CodiceValore dal XML
        tipo_codice: TipoCodice (EAN, FORNITORE, ecc.)
        descrizione: Descrizione della riga dal XML
        prezzo_netto_normalizzato: Prezzo dopo sconto (da confrontare)
        quantita: Quantità dalla riga
        unita_misura_fattura: UoM come arriva dal XML
        data_documento: Data della fattura (per determinare il listino valido)

    Returns:
        MatchResult con livello di match, delta calcolato, e suggerimenti
    """
    result = MatchResult()
    result.prezzo_fatturato_normalizzato = prezzo_netto_normalizzato

    # ── Livello 1: Match esatto su CodiceArticolo → Alias ──
    if codice_articolo:
        alias = await _match_by_alias(db, fornitore_id, codice_articolo)
        if alias:
            listino = await _get_listino_attivo(db, fornitore_id, alias.sku_interno, data_documento)
            if listino:
                result.matched = True
                result.livello = 1
                result.sku_interno = alias.sku_interno
                result.listino_id = listino.id
                result.prezzo_listino = listino.prezzo_pattuito
                await _applica_uom_e_calcola_delta(
                    db, result, listino, prezzo_netto_normalizzato, quantita, unita_misura_fattura, alias
                )
                return result

    # ── Livello 2: Match su EAN/barcode ──
    if codice_articolo and tipo_codice and tipo_codice.upper() in ("EAN", "EAN13", "EAN8", "GTIN"):
        # Cerca nel listino se il codice EAN corrisponde a uno SKU
        ean_alias = await _match_by_alias(db, fornitore_id, codice_articolo)
        if ean_alias:
            listino = await _get_listino_attivo(db, fornitore_id, ean_alias.sku_interno, data_documento)
            if listino:
                result.matched = True
                result.livello = 2
                result.sku_interno = ean_alias.sku_interno
                result.listino_id = listino.id
                result.prezzo_listino = listino.prezzo_pattuito
                await _applica_uom_e_calcola_delta(
                    db, result, listino, prezzo_netto_normalizzato, quantita, unita_misura_fattura, ean_alias
                )
                return result

    # ── Livello 3: Fuzzy match testuale — Spec §3.1 ──
    if descrizione:
        fuzzy = await _match_fuzzy(db, fornitore_id, descrizione, data_documento)
        if fuzzy:
            listino, confidenza = fuzzy
            if confidenza >= FUZZY_THRESHOLD:
                result.livello = 3
                result.confidenza = confidenza
                result.suggerimento_sku = listino.sku_interno
                result.suggerimento_desc = listino.descrizione
                # Il fuzzy NON è un match automatico — va proposto all'operatore
                # Ma calcoliamo comunque il delta potenziale
                result.prezzo_listino = listino.prezzo_pattuito
                result.listino_id = listino.id
                result.sku_interno = listino.sku_interno
                await _applica_uom_e_calcola_delta(
                    db, result, listino, prezzo_netto_normalizzato, quantita, unita_misura_fattura, None
                )
                return result

    # ── Livello 4: Nessun match → Parking Area ──
    result.livello = 4
    result.matched = False
    return result


# ─────────────────────────────────────────────
# Funzioni helper interne
# ─────────────────────────────────────────────

async def _match_by_alias(
    db: AsyncSession, fornitore_id: int, codice: str
) -> Optional[AliasProdotto]:
    """Livello 1/2: Cerca match esatto nella tabella AliasProdotti."""
    result = await db.execute(
        select(AliasProdotto).where(
            and_(
                AliasProdotto.fornitore_id == fornitore_id,
                AliasProdotto.codice_fornitore_originale == codice,
            )
        )
    )
    return result.scalar_one_or_none()


async def _get_listino_attivo(
    db: AsyncSession, fornitore_id: int, sku_interno: str, data_documento: str
) -> Optional[ListinoMaster]:
    """
    Trova il record ListinoMaster attivo alla data del documento.
    Append-Only: cerca il record con data_inizio <= data_doc
    e (data_scadenza IS NULL OR data_scadenza >= data_doc).
    """
    from datetime import date as date_type
    if isinstance(data_documento, str):
        try:
            doc_date = date_type.fromisoformat(data_documento)
        except ValueError:
            doc_date = date_type.today()
    else:
        doc_date = data_documento

    result = await db.execute(
        select(ListinoMaster)
        .where(
            and_(
                ListinoMaster.fornitore_id == fornitore_id,
                ListinoMaster.sku_interno == sku_interno,
                ListinoMaster.data_inizio_validita <= doc_date,
            )
        )
        .where(
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= doc_date)
        )
        .order_by(ListinoMaster.data_inizio_validita.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _match_fuzzy(
    db: AsyncSession, fornitore_id: int, descrizione_xml: str, data_documento: str
) -> Optional[tuple[ListinoMaster, float]]:
    """
    Livello 3: Fuzzy match su descrizione — Spec §3.1.
    Usa SequenceMatcher (basato su Levenshtein).
    Restituisce il miglior match sopra la soglia.
    """
    # Carica tutte le voci attive del fornitore
    from datetime import date as date_type
    if isinstance(data_documento, str):
        try:
            doc_date = date_type.fromisoformat(data_documento)
        except ValueError:
            doc_date = date_type.today()
    else:
        doc_date = data_documento

    result = await db.execute(
        select(ListinoMaster)
        .where(
            and_(
                ListinoMaster.fornitore_id == fornitore_id,
                ListinoMaster.data_inizio_validita <= doc_date,
            )
        )
        .where(
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= doc_date)
        )
    )
    listino_items = result.scalars().all()

    if not listino_items:
        return None

    desc_lower = descrizione_xml.lower().strip()
    best_match: Optional[ListinoMaster] = None
    best_score: float = 0.0

    for item in listino_items:
        item_desc = item.descrizione.lower().strip()
        # SequenceMatcher ratio — simile a distanza di Levenshtein normalizzata
        score = SequenceMatcher(None, desc_lower, item_desc).ratio()

        # Bonus: se il codice SKU è contenuto nella descrizione XML
        if item.sku_interno.lower() in desc_lower:
            score = min(score + 0.15, 1.0)

        if score > best_score:
            best_score = score
            best_match = item

    if best_match and best_score >= FUZZY_THRESHOLD:
        return (best_match, best_score)

    return None


async def _applica_uom_e_calcola_delta(
    db: AsyncSession,
    result: MatchResult,
    listino: ListinoMaster,
    prezzo_netto: Decimal,
    quantita: Decimal,
    uom_fattura: str | None,
    alias: Optional[AliasProdotto] = None,
) -> None:
    """
    Spec §3.2: Applica conversione UoM e calcola Delta.

    Se l'unità di misura della fattura è diversa da quella del listino,
    cerca il coefficiente in UoMConversioni e divide il prezzo fatturato.

    Delta = prezzo_fatturato_convertito - prezzo_listino
    """
    prezzo_confronto = prezzo_netto

    # ── Conversione UoM da Alias (Precedenza Massima) ──
    if alias and alias.coefficiente_conversione and alias.coefficiente_conversione != Decimal("1.0") and alias.coefficiente_conversione != Decimal("0"):
        result.coefficiente_uom = Decimal(str(alias.coefficiente_conversione))
        prezzo_confronto = (prezzo_netto / result.coefficiente_uom).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    # ── Conversione UoM se necessaria da Tabella UoM ──
    elif uom_fattura and listino.unita_misura and uom_fattura.lower() != listino.unita_misura.lower():
        conv_result = await db.execute(
            select(UoMConversione).where(
                and_(
                    UoMConversione.listino_id == listino.id,
                    UoMConversione.uom_fattura == uom_fattura,
                )
            )
        )
        conversione = conv_result.scalar_one_or_none()
        if conversione and conversione.coefficiente != Decimal("0"):
            result.coefficiente_uom = conversione.coefficiente
            prezzo_confronto = (prezzo_netto / conversione.coefficiente).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

    # ── Calcolo Delta — Spec §4.1 ──
    result.prezzo_listino = listino.prezzo_pattuito
    result.delta_prezzo = (prezzo_confronto - listino.prezzo_pattuito).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    result.delta_totale = (result.delta_prezzo * quantita).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
