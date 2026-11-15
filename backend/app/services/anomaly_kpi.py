"""KPI economici delle anomalie prezzo (card della Dashboard admin).

Un solo perimetro, lo stesso della lista anomalie (api/v1/anomalie.py):
tenant della fattura, anomalie operative (operational_anomaly_filter) e SKU
non esclusi. Prima la card "Attesa validazione" contava anche gli SKU esclusi.

Le note di credito stanno in due registri:
- note_di_credito (legacy, una per anomalia);
- dispute_credit_note_allocations, riassunte in dispute_case_anomalies.recovered_amount
  (note registrate dentro una pratica di contestazione).
"Recuperati" li somma entrambi senza contare due volte la stessa anomalia, e
"In reclamo" toglie quanto gia' recuperato nella pratica.
"""

from sqlalchemy import and_, case, exists, func, or_, select

from app.models.anomalie import Anomalia, NotaDiCredito, StatoValidazione
from app.models.disputes import DisputeCase, DisputeCaseAnomaly
from app.models.esclusi import SKUEscluso
from app.models.fatture import Fattura, RigaFattura
from app.models.location import Location
from app.services.anomaly_policy import operational_anomaly_filter
from app.services.tenant_scope import invoice_tenant_filter, location_tenant_filter


def sku_not_excluded_sql():
    """Stessa condizione della lista anomalie: righe senza SKU o SKU non escluso."""
    return or_(
        RigaFattura.sku_interno.is_(None),
        ~exists().where(SKUEscluso.sku_interno == RigaFattura.sku_interno),
    )


def _sum_when(state: StatoValidazione, amount):
    return func.coalesce(
        func.sum(case((Anomalia.stato_validazione == state, amount), else_=0)), 0
    )


def kpi_anomalies_statement(user):
    """in_contestazione (in_reclamo al netto del recuperato), a_rischio, attesa_manager."""
    recovered = func.coalesce(DisputeCaseAnomaly.recovered_amount, 0)
    residual = func.greatest(Anomalia.delta_totale - recovered, 0)
    return (
        select(
            _sum_when(StatoValidazione.in_reclamo, residual).label("in_contestazione"),
            _sum_when(StatoValidazione.contestata, Anomalia.delta_totale).label("a_rischio"),
            _sum_when(StatoValidazione.da_verificare, Anomalia.delta_totale).label("attesa_manager"),
        )
        .select_from(Anomalia)
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        # legacy_anomaly_id e' unico: al massimo una riga di pratica per anomalia.
        .outerjoin(DisputeCaseAnomaly, DisputeCaseAnomaly.legacy_anomaly_id == Anomalia.id)
        .where(
            invoice_tenant_filter(user),
            operational_anomaly_filter(),
            sku_not_excluded_sql(),
        )
    )


def kpi_recovered_statement(user):
    """Euro recuperati: note legacy + importi recuperati nelle pratiche, senza doppioni."""
    legacy = (
        select(func.coalesce(func.sum(NotaDiCredito.importo_recuperato), 0))
        .select_from(NotaDiCredito)
        .join(Anomalia, NotaDiCredito.anomalia_id == Anomalia.id)
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .where(invoice_tenant_filter(user))
        .scalar_subquery()
    )
    disputes = (
        select(func.coalesce(func.sum(DisputeCaseAnomaly.recovered_amount), 0))
        .select_from(DisputeCaseAnomaly)
        .join(DisputeCase, DisputeCase.id == DisputeCaseAnomaly.dispute_case_id)
        .where(
            DisputeCase.status != "cancelled",
            DisputeCase.location_id.in_(
                select(Location.id).where(location_tenant_filter(user))
            ),
            # Un'anomalia con una nota legacy e' gia' contata sopra.
            or_(
                DisputeCaseAnomaly.legacy_anomaly_id.is_(None),
                ~exists().where(
                    and_(NotaDiCredito.anomalia_id == DisputeCaseAnomaly.legacy_anomaly_id)
                ),
            ),
        )
        .scalar_subquery()
    )
    return select(legacy + disputes)
