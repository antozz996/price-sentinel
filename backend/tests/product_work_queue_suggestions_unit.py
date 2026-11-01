from types import SimpleNamespace

from app.api.v1.product_identity import _live_catalog_suggestion
from app.services.normalization import normalize_text


def product(product_id: int, name: str, **overrides):
    values = {
        "id": product_id,
        "sku_interno": f"SKU-{product_id}",
        "canonical_name": name,
        "normalized_name": normalize_text(name),
        "normalized_order_name": None,
        "volume_ml": None,
        "weight_g": None,
        "unit_count": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_exact_current_catalog_name_is_suggested_even_without_saved_candidate():
    raw = "Emperador calice vino 35cl 3-344272"
    match = _live_catalog_suggestion(raw, [product(7, raw, volume_ml=350)])

    assert match is not None
    assert match["product_id"] == 7
    assert match["score"] == 100
    assert match["reason_json"]["source"] == "live_catalog"


def test_near_identical_name_is_suggested_when_unambiguous():
    match = _live_catalog_suggestion(
        "Bicchiere long drink 370 ml impilabile",
        [
            product(8, "Bicchiere long drink 370ml impilabile", volume_ml=370),
            product(9, "Piatto fondo porcellana 24 cm"),
        ],
    )

    assert match is not None
    assert match["product_id"] == 8
    assert match["score"] >= 90


def test_conflicting_format_is_never_suggested():
    match = _live_catalog_suggestion(
        "Gelato vaniglia 2,8 kg",
        [product(10, "Gelato vaniglia 2,5 kg", weight_g=2500)],
    )

    assert match is None


def test_duplicate_exact_catalog_names_remain_for_manual_review():
    raw = "Basilico vaschetta"
    match = _live_catalog_suggestion(raw, [product(11, raw), product(12, raw)])

    assert match is None
