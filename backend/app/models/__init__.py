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
from app.models.anomalie import Anomalia, NotaDiCredito, ApprovazionePrezzo  # noqa: F401
from app.models.alias import AliasProdotto  # noqa: F401
from app.models.ordini import Ordine, RigaOrdine  # noqa: F401
from app.models.esclusi import SKUEscluso  # noqa: F401
from app.models.products import (  # noqa: F401
    Product,
    SupplierProductAlias,
    ProductEquivalenceGroup,
    ProductEquivalenceGroupItem,
    MatchCandidate,
)
from app.models.liquidstock_integration import (  # noqa: F401
    LiquidStockIntegrationEvent,
    LiquidStockSupplierOrder,
    LiquidStockSupplierOrderItem,
)
from app.models.purchase_order_reconciliation import (  # noqa: F401
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
    PurchaseOrderReconciliationItem,
)
from app.models.supplier_identity_equivalence import (  # noqa: F401
    SupplierIdentityEquivalence,
    SupplierIdentityEquivalenceAudit,
)
from app.models.disputes import (  # noqa: F401
    DisputeAttachment,
    DisputeAuditEvent,
    DisputeCase,
    DisputeCaseAnomaly,
    DisputeCommunication,
    DisputeCreditNote,
    DisputeCreditNoteAllocation,
    DisputeSupplierResponse,
)
from app.models.automation import AutomationAlert, AutomationRun  # noqa: F401
from app.models.feedbacks import ProductFeedback  # noqa: F401
from app.models.categories import MasterCategory  # noqa: F401
from app.models.onboarding import LocationReconciliationSettings  # noqa: F401
from app.models.purchase_policy import (  # noqa: F401
    ProductPurchasePolicy,
    ProductPurchasePolicyAudit,
    ProductSupplierAssessment,
    ProductSupplierAssessmentAudit,
    PurchasePolicyDeviation,
    SmartPriceSheetPreview,
    SupplierCategoryCapability,
)

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
    "ApprovazionePrezzo",
    "Ordine",
    "RigaOrdine",
    "ProductFeedback",
    "SKUEscluso",
    "Product",
    "SupplierProductAlias",
    "ProductEquivalenceGroup",
    "ProductEquivalenceGroupItem",
    "MatchCandidate",
    "LiquidStockIntegrationEvent",
    "LiquidStockSupplierOrder",
    "LiquidStockSupplierOrderItem",
    "SupplierIdentityEquivalence",
    "SupplierIdentityEquivalenceAudit",
    "AutomationAlert",
    "AutomationRun",
    "LocationReconciliationSettings",
    "ProductPurchasePolicy",
    "ProductPurchasePolicyAudit",
    "ProductSupplierAssessment",
    "ProductSupplierAssessmentAudit",
    "PurchasePolicyDeviation",
    "SmartPriceSheetPreview",
    "SupplierCategoryCapability",
    "MasterCategory",
]
