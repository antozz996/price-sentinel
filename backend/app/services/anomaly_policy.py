"""Shared policy for suppressing immaterial price-rounding noise."""

from decimal import Decimal

from sqlalchemy import delete, func, or_

from app.models.anomalie import Anomalia, StatoValidazione


MIN_ANOMALY_TOTAL = Decimal("0.10")

# States in which nobody has acted on the anomaly yet. Anything else (a dispute,
# a claim, a resolution) is an audit record and must not vanish on re-mapping.
UNWORKED_ANOMALY_STATES = (
    StatoValidazione.da_verificare,
    StatoValidazione.in_parking,
)

# Someone is acting on these: they stay visible until closed, whatever the amount.
OPEN_WORKED_ANOMALY_STATES = (
    StatoValidazione.proposta_aggiornamento,
    StatoValidazione.contestata,
    StatoValidazione.in_reclamo,
)


def is_material_price_increase(delta_total: Decimal | float | int) -> bool:
    """Return true only when the total overcharge reaches ten euro cents."""
    return Decimal(str(delta_total)) >= MIN_ANOMALY_TOTAL


def operational_anomaly_filter():
    """SQL condition for anomalies shown operationally: material or still being handled."""
    return or_(
        func.abs(Anomalia.delta_totale) >= MIN_ANOMALY_TOTAL,
        Anomalia.stato_validazione.in_(OPEN_WORKED_ANOMALY_STATES),
    )


def delete_stale_unworked_anomalies(riga_fattura_id: int):
    """Statement clearing an outdated, untouched anomaly after a line is re-priced."""
    return delete(Anomalia).where(
        Anomalia.riga_fattura_id == riga_fattura_id,
        Anomalia.stato_validazione.in_(UNWORKED_ANOMALY_STATES),
    )
