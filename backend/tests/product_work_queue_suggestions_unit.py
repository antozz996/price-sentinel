from types import SimpleNamespace

import app.api.v1.product_identity as product_identity
from app.api.v1.product_identity import (
    _build_live_catalog_index,
    _live_catalog_suggestion,
    _live_catalog_suggestions,
)
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
    matches = _live_catalog_suggestions(raw, [product(11, raw), product(12, raw)])

    assert len(matches) == 2
    assert all(match["score"] < 85 for match in matches)
    assert all(match["reason_json"]["ambiguous"] for match in matches)


def test_supplier_code_noise_and_word_order_still_produce_review_suggestion():
    match = _live_catalog_suggestion(
        "Rock Bar bicchiere Long Drink 370ml 36 pezzi impilabile 516170MEP021990",
        [product(13, "Bicchiere Rock Bar impilabile 36 pezzi Long Drink 370 ml", volume_ml=370, unit_count=36)],
    )

    assert match is not None
    assert match["product_id"] == 13
    assert match["score"] >= 70


def test_inverted_index_avoids_full_catalog_pairwise_comparisons():
    products = [product(index, f"Articolo completamente differente {index}") for index in range(1, 501)]
    products.append(product(900, "Bicchiere long drink impilabile 370 ml", volume_ml=370))
    catalog_index = _build_live_catalog_index(products)
    calls = 0
    original = product_identity._description_similarity

    def tracked(left, right):
        nonlocal calls
        calls += 1
        return original(left, right)

    product_identity._description_similarity = tracked
    try:
        matches = _live_catalog_suggestions(
            "Bicchiere long drink 370ml impilabile COD998877",
            products,
            catalog_index,
        )
    finally:
        product_identity._description_similarity = original

    assert matches and matches[0]["product_id"] == 900
    assert calls <= 3


def test_lower_confidence_candidate_is_visible_only_for_manual_review():
    match = _live_catalog_suggestion(
        "Bicchiere vino trasparente professionale",
        [product(901, "Bicchiere trasparente da vino")],
    )

    assert match is not None
    assert 55 <= match["score"] < 85


if __name__ == "__main__":
    test_exact_current_catalog_name_is_suggested_even_without_saved_candidate()
    test_near_identical_name_is_suggested_when_unambiguous()
    test_conflicting_format_is_never_suggested()
    test_duplicate_exact_catalog_names_remain_for_manual_review()
    test_supplier_code_noise_and_word_order_still_produce_review_suggestion()
    test_inverted_index_avoids_full_catalog_pairwise_comparisons()
    test_lower_confidence_candidate_is_visible_only_for_manual_review()
    print("PASS: live work-queue suggestions are accurate and format-safe")
