"""Shared policy for suppressing immaterial price-rounding noise."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anomalie import Anomalia, AnomaliaArchiviata, StatoValidazione


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


async def invoice_in_check_scope(db: AsyncSession, xml_raw_id: int | None) -> bool:
    """False for invoices uploaded before ANOMALY_CHECK_START: they never create anomalies."""
    from app.config import settings
    from app.models.fatture import XMLRaw

    start = settings.ANOMALY_CHECK_START
    if start is None:
        return True
    if xml_raw_id is None:
        return False
    received = await db.scalar(select(XMLRaw.data_ricezione).where(XMLRaw.id == xml_raw_id))
    return received is not None and received >= start


def is_material_price_increase(delta_total: Decimal | float | int) -> bool:
    """Return true only when the total overcharge reaches ten euro cents."""
    return Decimal(str(delta_total)) >= MIN_ANOMALY_TOTAL


def operational_anomaly_filter():
    """SQL condition for anomalies shown operationally: material or still being handled."""
    return or_(
        func.abs(Anomalia.delta_totale) >= MIN_ANOMALY_TOTAL,
        Anomalia.stato_validazione.in_(OPEN_WORKED_ANOMALY_STATES),
    )


def stale_unworked_anomaly_conditions(riga_fattura_id: int) -> tuple:
    """Conditions selecting an outdated, untouched anomaly after a line is re-priced."""
    return (
        Anomalia.riga_fattura_id == riga_fattura_id,
        Anomalia.stato_validazione.in_(UNWORKED_ANOMALY_STATES),
    )


def _json_value(value):
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


async def archive_and_remove_anomalies(db: AsyncSession, *conditions, reason: str) -> int:
    """
    Remove anomalies only after copying every column into anomalie_archiviate.
    Callers re-create the operational anomaly when needed: the history stays.
    """
    rows = (await db.scalars(select(Anomalia).where(*conditions))).all()
    if not rows:
        return 0
    for row in rows:
        db.add(
            AnomaliaArchiviata(
                anomalia_id=row.id,
                riga_fattura_id=row.riga_fattura_id,
                stato_validazione=_json_value(row.stato_validazione),
                delta_totale=row.delta_totale,
                motivo=reason,
                snapshot={column.name: _json_value(getattr(row, column.name)) for column in Anomalia.__table__.columns},
            )
        )
    await db.flush()
    await db.execute(delete(Anomalia).where(Anomalia.id.in_([row.id for row in rows])))
    return len(rows)


async def remove_stale_unworked_anomalies(db: AsyncSession, riga_fattura_id: int) -> int:
    return await archive_and_remove_anomalies(
        db,
        *stale_unworked_anomaly_conditions(riga_fattura_id),
        reason="riassociazione_sotto_soglia",
    )
