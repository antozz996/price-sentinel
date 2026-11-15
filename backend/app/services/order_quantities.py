"""Quantità di un ordine per unità (Registro ordini).

Le righe d'ordine hanno unità diverse (CT, conf, Kg, Lt, Pz): non si sommano tra
loro. I "colli" sono solo le righe a collo (cartone, confezione, cassa); gli omaggi
5+1 sono cartoni consegnati davvero, quindi restano nei colli e si mostrano a
parte come "di cui omaggio". Unità normalizzate con la base comune purchase_lines.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.services.purchase_lines import normalized_unit

# Unità normalizzate che sono colli. Una riga d'ordine senza unità nasce come CT
# (ordini.py salva uom or "CT").
PACK_UNITS = frozenset({"CT", "CNF", "CS", "COL", "COLLI", "COLLO", "BOX", "CASSA", "CASSE"})


def _number(value: Any) -> float:
    return float(value or 0)


def order_line_unit(uom: Any) -> str:
    return normalized_unit(uom or "CT")


def is_free_order_line(riga: Any) -> bool:
    """Omaggio: riga salvata come omaggio o con prezzo 0 (stessa regola della creazione ordine)."""
    return getattr(riga, "stato_ottimizzazione", None) == "omaggio" or _number(getattr(riga, "prezzo_inserito", 0)) == 0


def order_quantity_summary(righe: Iterable[Any]) -> dict:
    """Totali di un ordine senza mescolare le unità.

    quantita_per_uom / quantita_ricevuta_per_uom: {unità normalizzata: quantità};
    totale_colli / totale_colli_ricevuti: solo righe a collo, omaggi compresi;
    colli_omaggio: di cui omaggio.
    """
    ordered: dict[str, float] = {}
    received: dict[str, float] = {}
    colli = colli_ricevuti = colli_omaggio = 0.0
    for riga in righe:
        unit = order_line_unit(getattr(riga, "uom", None))
        quantity = _number(getattr(riga, "quantita", 0))
        quantity_received = _number(getattr(riga, "quantita_ricevuta", 0))
        ordered[unit] = round(ordered.get(unit, 0.0) + quantity, 3)
        received[unit] = round(received.get(unit, 0.0) + quantity_received, 3)
        if unit in PACK_UNITS:
            colli += quantity
            colli_ricevuti += quantity_received
            if is_free_order_line(riga):
                colli_omaggio += quantity
    return {
        "quantita_per_uom": ordered,
        "quantita_ricevuta_per_uom": received,
        "totale_colli": round(colli, 3),
        "totale_colli_ricevuti": round(colli_ricevuti, 3),
        "colli_omaggio": round(colli_omaggio, 3),
    }
