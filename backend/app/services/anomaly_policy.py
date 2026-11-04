"""Shared policy for suppressing immaterial price-rounding noise."""

from decimal import Decimal


MIN_ANOMALY_TOTAL = Decimal("0.10")


def is_material_price_increase(delta_total: Decimal | float | int) -> bool:
    """Return true only when the total overcharge reaches ten euro cents."""
    return Decimal(str(delta_total)) >= MIN_ANOMALY_TOTAL
