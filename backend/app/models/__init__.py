"""
Price Sentinel — Models package.
Importa tutti i modelli per Alembic autogenerate.
"""

from app.database import Base  # noqa: F401 — Base necessaria per metadata

from app.models.utenti import Utente  # noqa: F401
from app.models.location import Location  # noqa: F401
from app.models.fornitori import Fornitore  # noqa: F401
from app.models.listino import ListinoMaster, PFAScaglione, UoMConversione  # noqa: F401
from app.models.fatture import XMLRaw, Fattura, RigaFattura  # noqa: F401
from app.models.anomalie import Anomalia, NotaDiCredito  # noqa: F401
from app.models.alias import AliasProdotto  # noqa: F401

__all__ = [
    "Base",
    "Utente",
    "Location",
    "Fornitore",
    "ListinoMaster",
    "PFAScaglione",
    "UoMConversione",
    "XMLRaw",
    "Fattura",
    "RigaFattura",
    "Anomalia",
    "NotaDiCredito",
    "AliasProdotto",
]
