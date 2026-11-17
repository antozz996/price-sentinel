"""Regole del listino sempre aperto (decise con l'ufficio acquisti il 17/11/2026).

- Ribasso: vale subito.
- Aumento: si carica quando si vuole, ma vale dalla prossima data fissa (1 o 15 del mese).
  Un aumento caricato proprio il 1 o il 15 vale dalla data fissa successiva:
  il listino va consegnato prima della data.
- Conta l'ultimo caricamento: una nuova modifica dello stesso prodotto sostituisce
  quella in attesa (un ribasso annulla l'aumento programmato).
- Restano sospese finché l'ufficio non le guarda: ribasso oltre il 40%, aumento oltre
  il 30%, offerta aggiuntiva su un prodotto che il fornitore ha già a listino.
- "Non lo tratto più": il prezzo resta valido fino alla prossima data fissa, poi si chiude.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.models.supplier_price_link import (
    STATO_PROGRAMMATO,
    STATO_TRATTENUTO,
    TIPO_AUMENTO,
    TIPO_INVARIATO,
    TIPO_NON_TRATTATO,
    TIPO_NUOVA_OFFERTA,
    TIPO_RIBASSO,
)

ROME = ZoneInfo("Europe/Rome")
SOGLIA_RIBASSO = Decimal("0.40")
SOGLIA_AUMENTO = Decimal("0.30")


def today_rome(now: datetime | None = None) -> date:
    return (now or datetime.now(ROME)).astimezone(ROME).date()


def next_fixed_date(today: date) -> date:
    """Prima data fissa (1 o 15) strettamente successiva a oggi."""
    if today.day < 15:
        return today.replace(day=15)
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


@dataclass(frozen=True)
class ChangeDecision:
    tipo: str
    stato: str | None          # None = nessuna modifica da salvare (prezzo invariato)
    decorrenza: date
    motivo_trattenuta: str | None = None


def decide_change(
    *,
    today: date,
    prezzo_vecchio: Decimal | None,
    prezzo_nuovo: Decimal | None,
    non_trattato: bool = False,
    altra_offerta_attiva: bool = False,
) -> ChangeDecision:
    """Che cosa succede a una riga inviata dal fornitore tramite il link fisso."""
    if non_trattato:
        return ChangeDecision(TIPO_NON_TRATTATO, STATO_PROGRAMMATO, next_fixed_date(today))
    if prezzo_nuovo is None or prezzo_nuovo <= 0:
        raise ValueError("Prezzo mancante o non valido")
    if prezzo_vecchio is None:
        if altra_offerta_attiva:
            return ChangeDecision(TIPO_NUOVA_OFFERTA, STATO_TRATTENUTO, today,
                                  "Offerta aggiuntiva su un prodotto già quotato")
        return ChangeDecision(TIPO_NUOVA_OFFERTA, STATO_PROGRAMMATO, today)
    if prezzo_nuovo == prezzo_vecchio:
        return ChangeDecision(TIPO_INVARIATO, None, today)
    variazione = (prezzo_nuovo - prezzo_vecchio) / prezzo_vecchio
    if variazione < 0:
        if -variazione > SOGLIA_RIBASSO:
            return ChangeDecision(TIPO_RIBASSO, STATO_TRATTENUTO, today,
                                  f"Ribasso oltre il {SOGLIA_RIBASSO:.0%}")
        return ChangeDecision(TIPO_RIBASSO, STATO_PROGRAMMATO, today)
    decorrenza = next_fixed_date(today)
    if variazione > SOGLIA_AUMENTO:
        return ChangeDecision(TIPO_AUMENTO, STATO_TRATTENUTO, decorrenza,
                              f"Aumento oltre il {SOGLIA_AUMENTO:.0%}")
    return ChangeDecision(TIPO_AUMENTO, STATO_PROGRAMMATO, decorrenza)


def offer_lock_key(fornitore_id: int, chiave_offerta: str) -> int:
    """Chiave per pg_advisory_xact_lock: un solo scrittore per offerta del fornitore."""
    digest = hashlib.sha256(f"listino-aperto:{fornitore_id}:{chiave_offerta}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)
