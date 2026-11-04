from decimal import Decimal

from app.services.anomaly_policy import is_material_price_increase


def test_rounding_noise_is_not_an_anomaly():
    assert not is_material_price_increase(Decimal("0.00"))
    assert not is_material_price_increase(Decimal("0.04"))
    assert not is_material_price_increase(Decimal("0.0999"))


def test_ten_cents_is_material():
    assert is_material_price_increase(Decimal("0.10"))
    assert is_material_price_increase(Decimal("5.00"))
