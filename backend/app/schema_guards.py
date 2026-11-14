"""Vincoli di schema applicati all'avvio solo quando i dati li rispettano già.

L'avvio non deve mai fallire per colpa dei dati: se un vincolo non si può
creare (per esempio fatture doppie ancora presenti) si scrive un avviso e
l'applicazione parte senza vincolo; al riavvio successivo, dopo la pulizia
dei dati, il vincolo viene creato.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger("price_sentinel.schema")

FATTURE_XML_RAW_UNIQUE_INDEX = "uq_fatture_xml_raw_id"

COUNT_DUPLICATE_XML_RAW_SQL = (
    "SELECT count(*) FROM ("
    "SELECT xml_raw_id FROM fatture GROUP BY xml_raw_id HAVING count(*) > 1"
    ") AS doppie"
)
CREATE_FATTURE_XML_RAW_UNIQUE_SQL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {FATTURE_XML_RAW_UNIQUE_INDEX} "
    "ON fatture (xml_raw_id)"
)


async def ensure_unique_invoice_per_xml(conn) -> bool:
    """Crea l'indice UNIQUE su fatture(xml_raw_id) se non ci sono doppioni.

    Restituisce True se l'indice esiste (creato ora o già presente), False se
    è stato saltato perché ci sono ancora XML con più di una fattura.
    """
    duplicates = await conn.scalar(text(COUNT_DUPLICATE_XML_RAW_SQL))
    if duplicates:
        logger.warning(
            "Indice %s non creato: %s xml_raw hanno più di una fattura. "
            "Cancellare le fatture doppie e riavviare.",
            FATTURE_XML_RAW_UNIQUE_INDEX,
            duplicates,
        )
        return False
    await conn.execute(text(CREATE_FATTURE_XML_RAW_UNIQUE_SQL))
    return True
